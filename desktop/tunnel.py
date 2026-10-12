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
from pathlib import Path
from typing import IO, Optional, Sequence

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
    found = shutil.which("cloudflared")
    if found:
        return found
    return next((str(p) for p in _known_locations() if p.is_file()), None)


def install_cloudflared() -> str:
    """Install cloudflared with the system's package manager; returns its path."""
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


def _read_lines(stream: IO[str], lines: "queue.Queue[str]") -> None:
    # Keep reading after the address shows up: a full pipe would stall cloudflared.
    for line in stream:
        lines.put(line)


class Tunnel:
    """One quick tunnel to a local port, open until ``stop``."""

    def __init__(self, port: int, command: Optional[Sequence[str]] = None) -> None:
        self.port = port
        self._command = list(command) if command else None
        self._process: Optional[subprocess.Popen] = None
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

        lines: "queue.Queue[str]" = queue.Queue()
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
