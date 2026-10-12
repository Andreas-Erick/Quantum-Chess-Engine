"""Internet play for the desktop app: a Cloudflare quick tunnel to the hosting listener.

Hosting only reaches the local network, because a home router keeps other machines out. A quick
tunnel (``cloudflared tunnel --url ...``) gives the listener a temporary public address,
``https://<random words>.trycloudflare.com``, with no Cloudflare account. It forwards to the
same ``GuestsOnly`` listener as hosting, so guests from the internet can do exactly what guests
on the network can: join, watch and play the host's online games.

cloudflared is a separate program. If it isn't installed, the app installs it with the system's
package manager (winget on Windows, Homebrew on macOS), which checks the download.
"""

from __future__ import annotations

import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import IO, Any, Optional, cast

PUBLIC_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
START_TIMEOUT = 45.0  # seconds; a quick tunnel usually takes 5 to 15
# Run without a console window popping up next to the app (Windows only).
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class TunnelError(RuntimeError):
    """The tunnel could not be opened; the message says why, for the player."""


def _known_locations() -> list[Path]:
    # A windowed app may not see the PATH of a terminal, so look where installers put it.
    if sys.platform == "win32":
        roots = [os.environ.get(k) for k in ("ProgramFiles", "ProgramFiles(x86)")]
        places = [Path(r) / "cloudflared" / "cloudflared.exe" for r in roots if r]
        local = os.environ.get("LOCALAPPDATA")
        if local:
            places.append(Path(local) / "Microsoft" / "WinGet" / "Links" / "cloudflared.exe")
        return places
    return [Path("/opt/homebrew/bin/cloudflared"), Path("/usr/local/bin/cloudflared")]


def find_cloudflared() -> Optional[str]:
    # Installers' own folders first: the PATH (or, on Windows, the current folder) could hold
    # something else named cloudflared.
    known = next((str(p) for p in _known_locations() if p.is_file()), None)
    return known or shutil.which("cloudflared")


def install_cloudflared() -> str:
    """Install cloudflared with the system's package manager; returns its path."""
    command: list[str]
    if sys.platform == "win32" and shutil.which("winget"):
        command = [
            "winget", "install", "--id", "Cloudflare.cloudflared", "--exact", "--silent",
            "--accept-package-agreements", "--accept-source-agreements",
        ]  # fmt: skip
    elif sys.platform == "darwin" and (
        shutil.which("brew") or Path("/opt/homebrew/bin/brew").is_file()
    ):
        command = [shutil.which("brew") or "/opt/homebrew/bin/brew", "install", "cloudflared"]
    else:
        raise TunnelError(
            "Internet play needs cloudflared. Install it from "
            "https://github.com/cloudflare/cloudflared/releases and try again."
        )
    try:
        subprocess.run(command, capture_output=True, timeout=600, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TunnelError(f"Installing cloudflared failed: {exc}") from exc
    path = find_cloudflared()
    if not path:
        raise TunnelError(
            "Installing cloudflared didn't work. Install it from "
            "https://github.com/cloudflare/cloudflared/releases and try again."
        )
    return path


def _close_with_this_process(process: subprocess.Popen) -> Any:
    """Windows: put the process in a job that Windows closes when this one exits, even by a
    crash, so the tunnel can't outlive the app and later forward to another program on the
    same port. Returns the job's handle, which must stay open until then."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class Basic(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class Extended(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", Basic),
            ("IoInfo", ctypes.c_ulonglong * 6),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kill_on_job_close, extended_limit_information = 0x2000, 9
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD
    ]  # fmt: skip
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    job = kernel32.CreateJobObjectW(None, None)
    info = Extended()
    info.BasicLimitInformation.LimitFlags = kill_on_job_close
    if not (
        job
        and kernel32.SetInformationJobObject(
            job, extended_limit_information, ctypes.byref(info), ctypes.sizeof(info)
        )
        # Popen's process handle: private, but the only way to it on Windows.
        and kernel32.AssignProcessToJobObject(job, int(cast(Any, process)._handle))
    ):
        raise TunnelError("Could not tie the internet link to the app, so it wasn't opened.")
    return job


def _read_lines(stream: IO[str], lines: queue.Queue[str]) -> None:
    # Keep reading after the address shows up: a full pipe would stall cloudflared.
    for line in stream:
        lines.put(line)


class Tunnel:
    """One quick tunnel to a local port, open until ``stop``."""

    def __init__(self, port: int, command: Optional[Sequence[str]] = None) -> None:
        self.port = port
        self._command = list(command) if command else None
        self._process: Optional[subprocess.Popen] = None
        self._job: Any = None
        self.url: Optional[str] = None

    def start(self, timeout: float = START_TIMEOUT) -> str:
        """Open the tunnel; returns its public address once cloudflared reports it."""
        program = self._command or [find_cloudflared() or install_cloudflared()]
        args = ["tunnel", "--no-autoupdate", "--url", f"http://localhost:{self.port}"]
        try:
            self._process = subprocess.Popen(
                [*program, *args],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,  # cloudflared logs, including the address, to stderr
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=NO_WINDOW,
            )
        except OSError as exc:
            raise TunnelError(f"Could not start cloudflared: {exc}") from exc
        try:
            self._job = _close_with_this_process(self._process)
        except TunnelError:
            self.stop()
            raise

        lines: queue.Queue[str] = queue.Queue()
        assert self._process.stderr is not None
        threading.Thread(
            target=_read_lines, args=(self._process.stderr, lines), name="tunnel-log", daemon=True
        ).start()
        recent: list[str] = []
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                line = lines.get(timeout=0.25)
            except queue.Empty:
                if self._process.poll() is not None and lines.empty():
                    break
                continue
            recent = (recent + [line.strip()])[-5:]
            match = PUBLIC_URL.search(line)
            if match:
                self.url = match.group(0)
                return self.url
        self.stop()
        detail = " ".join(recent) or "no output"
        raise TunnelError(f"The internet link could not be opened ({detail}).")

    def stop(self) -> None:
        process, self._process, self.url = self._process, None, None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        job, self._job = self._job, None
        if job and sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32")
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle(job)
