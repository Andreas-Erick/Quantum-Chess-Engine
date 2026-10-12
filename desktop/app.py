"""Quantum Chess as a desktop app: the engine runs in-process, the UI in a native window.

    python -m desktop                       # play locally; host or join friends from the app
    python -m desktop --lan                 # start hosting on your network right away
    python -m desktop --server https://...  # open a hosted server instead of a local one

The window is a system web view (Edge WebView2 on Windows, WebKit on macOS, GTK or Qt on Linux),
so the app shows exactly the web UI, served by the same FastAPI app as the Docker image.

Playing a friend: one app *hosts* (its server starts listening on the local network, and the
invite link points there) and the other *joins* by pasting the link. Joining happens in this
Python code rather than in the page: the joiner's share of the dice (see api/fairness.py) is
generated and kept here, where the host can't see or replace it, so the joiner can verify the
finished game from the Game menu.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlsplit

APP_NAME = "Quantum Chess"


def bundle_dir() -> Path:
    """The project root, or the unpacked bundle when frozen by PyInstaller."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    """Where the app keeps its browser storage, joined games and log."""
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


def start_server(
    host: str, port: int, app: Any = None, ui_dir: Optional[Path] = None, timeout: float = 30.0
):
    """Serve ``app`` (by default a new API + UI app) from a background thread; returns the
    uvicorn server once it listens. Several servers can share one app, and so its games."""
    import uvicorn

    from api.server import create_app

    if app is None:
        app = create_app(ui_dir=ui_dir) if ui_dir is not None else create_app()
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, name=f"server-{host}:{port}", daemon=True)
    thread.start()
    deadline = time.monotonic() + timeout
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError(f"the engine did not start on {host}:{port}")
        time.sleep(0.05)
    return server


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def game_of(url: str) -> Optional[str]:
    query = parse_qs(urlsplit(url).query)
    return (query.get("game") or query.get("join") or [None])[0]


class JoinedGames:
    """The games this app joined, with the seed it contributed to each (data_dir/joined.json)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def seed(self, origin: str, game_id: str) -> Optional[str]:
        return self._read().get(f"{origin}/{game_id}", {}).get("seed")

    def add(self, origin: str, game_id: str, seat: dict) -> None:
        with self._lock:
            games = self._read()
            games[f"{origin}/{game_id}"] = seat
            self.path.write_text(json.dumps(games, indent=2), encoding="utf-8")


def join_game(link: str, joined: JoinedGames) -> str:
    """Join the game an invite link points at, with a seed generated here. Returns the address
    to open: the game, with the seat handed to the page in the fragment (never sent to a server)."""
    import httpx

    parts = urlsplit(link.strip())
    game_id = game_of(link.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc or not game_id:
        raise ValueError("That doesn't look like an invite link (http://…/?join=…).")
    origin = origin_of(link.strip())
    seed = secrets.token_hex(32)
    try:
        response = httpx.post(
            f"{origin}/online/join", json={"game_id": game_id, "seed": seed}, timeout=10
        )
    except httpx.HTTPError as exc:
        raise ConnectionError(f"Could not reach {origin}. Is the host on your network?") from exc
    game_url = f"{origin}/?game={game_id}"
    if response.status_code == 409:  # both seats taken: watch instead
        return game_url
    if response.status_code != 200:
        raise ValueError(response.json().get("detail", f"joining failed ({response.status_code})"))
    seat = response.json()
    joined.add(origin, game_id, {"color": seat["color"], "seed": seed})
    return f"{game_url}#seat={seat['color']}.{seat['token']}"


class Desktop:
    """What the page can ask of the app, as ``window.pywebview.api``. Every page in the window
    gets this bridge, including a host's page after joining, so anything that acts on this
    machine (hosting, joining) is refused unless the page is this app's own."""

    def __init__(self, app: Any, local_url: Optional[str], joined: JoinedGames) -> None:
        self._app = app
        self._local_url = local_url
        self._lan_url: Optional[str] = None
        self._joined = joined
        self._window: Any = None
        self._lock = threading.Lock()

    def _on_own_page(self) -> bool:
        current = self._window.get_current_url() if self._window else None
        return bool(
            self._local_url and current and origin_of(current) == origin_of(self._local_url)
        )

    def _start_hosting(self) -> str:
        with self._lock:
            if self._lan_url is None:
                port = free_port("0.0.0.0")
                start_server("0.0.0.0", port, self._app)
                self._lan_url = f"http://{lan_address()}:{port}"
            return self._lan_url

    # --- Exposed to the page ---------------------------------------------------------

    def info(self) -> dict:
        return {"local_url": self._local_url, "lan_url": self._lan_url}

    def host(self) -> str:
        """Start accepting players from the local network; returns the address to invite to."""
        if not self._on_own_page():
            raise PermissionError("only the app's own page can start hosting")
        return self._start_hosting()

    def join(self, link: str) -> None:
        if not self._on_own_page():
            raise PermissionError("only the app's own page can join games")
        self._window.load_url(join_game(link, self._joined))

    def home(self) -> None:
        if self._local_url:
            self._window.load_url(self._local_url)

    # --- Menu ------------------------------------------------------------------------

    def verify_current(self) -> None:
        """Check the open game's dice and say so in a native dialog the page can't fake."""
        import httpx

        from api.fairness import verify

        url = self._window.get_current_url() or ""
        game_id = game_of(url)
        if not game_id:
            message = "Open a finished online game first."
        elif self._on_own_page() or (self._lan_url and url.startswith(self._lan_url)):
            message = "You hosted this game: the dice were rolled by your own app."
        else:
            try:
                state = httpx.get(
                    f"{origin_of(url)}/state", params={"game_id": game_id}, timeout=10
                ).json()
                verdict = verify(state, self._joined.seed(origin_of(url), game_id))
                message = ("Fair. " if verdict.fair else "Not verified. ") + verdict.reason
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                message = f"Could not check this game: {exc}"
        self._window.create_confirmation_dialog("Verify dice", message)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="quantum-chess", description=__doc__.splitlines()[0])
    where = parser.add_mutually_exclusive_group()
    where.add_argument("--server", help="open this server instead of starting one locally")
    where.add_argument("--lan", action="store_true", help="start hosting on your network")
    parser.add_argument("--port", type=int, default=0, help="local port (default: any free one)")
    parser.add_argument("--debug", action="store_true", help="enable the web inspector")
    return parser.parse_args(argv)


def redirect_output() -> None:
    """A windowed build has no console, so output and errors would vanish. Send them to a log
    file in the data directory instead."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    log = open(data_dir() / "quantum-chess.log", "w", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or log
    sys.stderr = sys.stderr or log


def main(argv: Optional[list[str]] = None) -> None:
    redirect_output()
    args = parse_args(argv)
    joined = JoinedGames(data_dir() / "joined.json")
    if args.server:
        desktop = Desktop(None, None, joined)
        url = args.server
    else:
        from api.server import create_app

        ui_dir = bundle_dir() / "ui" / "dist"
        if not (ui_dir / "index.html").is_file():
            sys.exit(
                f"The UI is not built ({ui_dir} is missing). Run: cd ui && npm ci && npm run build"
            )
        app = create_app(ui_dir=ui_dir)
        port = args.port or free_port("127.0.0.1")
        start_server("127.0.0.1", port, app)
        url = f"http://127.0.0.1:{port}/"
        desktop = Desktop(app, url, joined)
        print(f"{APP_NAME} is running at {url}")
        if args.lan:
            print(f"Hosting on your network at {desktop._start_hosting()}")

    import webview
    from webview.menu import Menu, MenuAction, MenuSeparator

    desktop._window = webview.create_window(
        APP_NAME,
        url,
        js_api=desktop,
        width=1240,
        height=880,
        min_size=(720, 640),
        background_color="#f5f4f0",
    )
    menu = [
        Menu(
            "Game",
            [
                MenuAction("My games", desktop.home),
                MenuSeparator(),
                MenuAction("Verify this game's dice", desktop.verify_current),
            ],
        )
    ]
    # Not private: keep browser storage between runs so finished lessons stay ticked.
    webview.start(
        private_mode=False,
        storage_path=str(data_dir() / "webview"),
        debug=args.debug,
        menu=menu,
    )


if __name__ == "__main__":
    main()
