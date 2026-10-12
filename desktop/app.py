"""Quantum Chess as a desktop app: the engine runs in-process, the UI in a native window.

    python -m desktop                       # play locally (AI, tutorial, two players on one screen)
    python -m desktop --lan                 # also let a friend on your network join online games
    python -m desktop --server https://...  # open a hosted server, e.g. to play friends online

The window is a system web view (Edge WebView2 on Windows, WebKit on macOS, GTK or Qt on Linux),
so the app shows exactly the web UI, served by the same FastAPI app as the Docker image.
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Optional

APP_NAME = "Quantum Chess"


def bundle_dir() -> Path:
    """The project root, or the unpacked bundle when frozen by PyInstaller."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    """Where the window keeps its browser storage (resumed games, finished lessons)."""
    if sys.platform == "win32":
        root = Path(os.environ.get("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    path = root / "QuantumChess"
    path.mkdir(parents=True, exist_ok=True)
    return path


def free_port(host: str) -> int:
    with socket.socket() as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def lan_address() -> str:
    """This machine's address on the local network (no packets are sent)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("192.0.2.1", 80))  # TEST-NET-1: routable, never answered
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def start_server(host: str, port: int, ui_dir: Optional[Path] = None, timeout: float = 30.0):
    """Run the API (and UI) in a background thread; returns the uvicorn server once it listens."""
    import uvicorn

    from api.server import create_app

    app = create_app(ui_dir=ui_dir) if ui_dir is not None else create_app()
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, name="quantum-chess-server", daemon=True)
    thread.start()
    deadline = time.monotonic() + timeout
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError(f"the engine did not start on {host}:{port}")
        time.sleep(0.05)
    return server


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="quantum-chess", description=__doc__.splitlines()[0])
    where = parser.add_mutually_exclusive_group()
    where.add_argument("--server", help="open this server instead of starting one locally")
    where.add_argument(
        "--lan", action="store_true", help="accept connections from your network for online games"
    )
    parser.add_argument("--port", type=int, default=0, help="local port (default: any free one)")
    parser.add_argument("--debug", action="store_true", help="enable the web inspector")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)
    if args.server:
        url = args.server
    else:
        ui_dir = bundle_dir() / "ui" / "dist"
        if not (ui_dir / "index.html").is_file():
            sys.exit(
                f"The UI is not built ({ui_dir} is missing). Run: cd ui && npm ci && npm run build"
            )
        bind = "0.0.0.0" if args.lan else "127.0.0.1"
        port = args.port or free_port(bind)
        start_server(bind, port, ui_dir)
        # Invite links use the address in the window, so on a LAN it must be the LAN address.
        url = f"http://{lan_address() if args.lan else '127.0.0.1'}:{port}/"
        print(f"{APP_NAME} is running at {url}")

    import webview

    webview.create_window(
        APP_NAME, url, width=1240, height=880, min_size=(720, 640), background_color="#f5f4f0"
    )
    # Not private: keep browser storage between runs so finished lessons stay ticked.
    webview.start(private_mode=False, storage_path=str(data_dir() / "webview"), debug=args.debug)


if __name__ == "__main__":
    main()
