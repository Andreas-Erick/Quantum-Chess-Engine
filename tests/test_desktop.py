"""The desktop launcher: its embedded server, hosting, joining and dice verification.
(The native window needs a display, so a stand-in records what the app asks of it.)"""

import httpx
import pytest

from api.server import create_app
from desktop.app import (
    Desktop,
    GuestsOnly,
    JoinedGames,
    LocalOnly,
    free_port,
    join_game,
    parse_args,
    start_server,
    stop_server,
)

FEN = "k7/8/8/8/1n6/8/8/R3K3 b - - 0 1"  # see tests/test_fairness.py


class FakeWindow:
    def __init__(self, url: str) -> None:
        self.url = url
        self.dialogs: list[str] = []

    def get_current_url(self) -> str:
        return self.url

    def load_url(self, url: str) -> None:
        self.url = url

    def create_confirmation_dialog(self, title: str, message: str) -> bool:
        self.dialogs.append(message)
        return True


@pytest.fixture
def host_app():
    """A hosting player's app: its API on a local port."""
    app = create_app(ui_dir=None)
    port = free_port("127.0.0.1")
    server = start_server("127.0.0.1", port, app)
    yield app, f"http://127.0.0.1:{port}"
    server.should_exit = True


def make_desktop(app, url, tmp_path, name="joined.json"):
    desktop = Desktop(app, f"{url}/", JoinedGames(tmp_path / name))
    desktop._window = FakeWindow(f"{url}/")
    return desktop


def test_embedded_server_serves_api_and_ui(tmp_path):
    (tmp_path / "index.html").write_text("<title>Quantum Chess</title>")
    port = free_port("127.0.0.1")
    server = start_server("127.0.0.1", port, ui_dir=tmp_path)
    try:
        base = f"http://127.0.0.1:{port}"
        assert httpx.get(f"{base}/health").json() == {"status": "ok"}
        assert "Quantum Chess" in httpx.get(f"{base}/").text
    finally:
        server.should_exit = True


def test_options():
    assert parse_args([]).server is None and not parse_args([]).lan
    assert parse_args(["--server", "https://example.org"]).server == "https://example.org"
    assert parse_args(["--lan", "--port", "9000"]).port == 9000
    with pytest.raises(SystemExit):
        parse_args(["--lan", "--server", "https://example.org"])


def test_hosting_shares_the_games_on_a_second_listener(host_app, tmp_path):
    app, url = host_app
    desktop = make_desktop(app, url, tmp_path)
    lan = desktop.host()
    assert desktop.host() == lan  # started once
    assert desktop.info() == {"own_page": True, "lan_url": lan, "public_url": None}
    game_id = httpx.post(f"{url}/online/create", json={}).json()["game_id"]
    port = lan.rsplit(":", 1)[1]
    # The same game is reachable through the network listener.
    assert httpx.get(f"http://127.0.0.1:{port}/state", params={"game_id": game_id}).is_success


def test_network_guests_can_play_but_not_start_games(host_app, tmp_path):
    app, url = host_app
    desktop = make_desktop(app, url, tmp_path)
    lan = "http://127.0.0.1:" + desktop.host().rsplit(":", 1)[1]
    game_id = httpx.post(f"{url}/online/create", json={}).json()["game_id"]
    assert httpx.post(f"{lan}/online/join", json={"game_id": game_id}).is_success
    assert httpx.get(f"{lan}/state", params={"game_id": game_id}).is_success
    for path in ("/init", "/init/", "/%69nit", "/ai_move", "/online/create", "/online/%63reate"):
        response = httpx.post(f"{lan}{path}", json={"game_id": game_id})
        assert response.status_code == 403, path
        assert "Only the host" in response.json()["detail"]
    assert httpx.post(f"{url}/init", json={}).is_success  # the host still can


def test_stop_hosting_closes_the_network_listener(host_app, tmp_path):
    app, url = host_app
    desktop = make_desktop(app, url, tmp_path)
    lan = "http://127.0.0.1:" + desktop.host().rsplit(":", 1)[1]
    assert httpx.get(f"{lan}/health").is_success
    desktop.stop_hosting()
    assert desktop.info() == {"own_page": True, "lan_url": None, "public_url": None}
    with pytest.raises(httpx.ConnectError):
        httpx.get(f"{lan}/health")
    assert httpx.get(f"{url}/health").is_success  # the app itself keeps running
    assert desktop.host() != f"{lan}"  # and can host again, on a new port


def test_stop_server_returns_once_stopped():
    port = free_port("127.0.0.1")
    server = start_server("127.0.0.1", port, create_app(ui_dir=None))
    stop_server(server)
    assert not server.thread.is_alive()


def test_window_only_shows_pages_the_app_opened(host_app, tmp_path):
    app, url = host_app
    desktop = make_desktop(app, url, tmp_path)
    window = desktop._window
    for allowed in (f"{url}/?game=abc", "about:blank"):
        window.url = allowed
        desktop._check_page()
        assert window.url == allowed and window.dialogs == []
    window.url = "https://login.example.com/signin"  # a host's page sent the window here
    desktop._check_page()
    assert window.url == f"{url}/"
    assert "https://login.example.com" in window.dialogs[-1]


def test_a_joined_hosts_pages_are_allowed(host_app, tmp_path):
    app, url = host_app
    guest = Desktop(None, "http://127.0.0.1:1/", JoinedGames(tmp_path / "guest.json"))
    guest._window = FakeWindow("http://127.0.0.1:1/")
    game_id = httpx.post(f"{url}/online/create", json={}).json()["game_id"]
    guest.join(f"{url}/?join={game_id}")
    guest._window.url = f"{url}/?game=other"
    guest._check_page()
    assert guest._window.url == f"{url}/?game=other" and guest._window.dialogs == []


def test_server_mode_keeps_to_its_server(tmp_path):
    desktop = Desktop(None, None, JoinedGames(tmp_path / "j.json"), start_url="https://qc.example")
    desktop._window = FakeWindow("https://qc.example/?game=abc")
    desktop._check_page()
    assert desktop._window.dialogs == []
    desktop._window.url = "https://elsewhere.example/"
    desktop._check_page()
    assert desktop._window.url == "https://qc.example"
    desktop.home()
    assert desktop._window.url == "https://qc.example"


def test_foreign_pages_cannot_host_or_join(host_app, tmp_path):
    app, url = host_app
    desktop = make_desktop(app, url, tmp_path)
    desktop.host()
    desktop._window.url = "http://192.168.1.50:8000/?game=abc"  # a host's page, after joining
    assert desktop.info() == {"own_page": False, "lan_url": None, "public_url": None}
    with pytest.raises(PermissionError):
        desktop.host()
    with pytest.raises(PermissionError):
        desktop.share_online()
    with pytest.raises(PermissionError):
        desktop.stop_hosting()
    with pytest.raises(PermissionError):
        desktop.join("http://192.168.1.50:8000/?join=abc")
    desktop.home()
    assert desktop._window.url == f"{url}/"


def test_join_rejects_non_links(tmp_path):
    with pytest.raises(ValueError):
        join_game("not a link", JoinedGames(tmp_path / "j.json"))
    with pytest.raises(ValueError):
        join_game("http://example.org/", JoinedGames(tmp_path / "j.json"))


def test_join_unreachable_host_explains(tmp_path):
    port = free_port("127.0.0.1")  # nothing listens here
    with pytest.raises(ConnectionError):
        join_game(f"http://127.0.0.1:{port}/?join=abc", JoinedGames(tmp_path / "j.json"))


def test_host_join_play_and_verify(host_app, tmp_path):
    app, url = host_app
    # A second app joins from invite links; it keeps its seeds and opens the games.
    guest = Desktop(None, "http://127.0.0.1:1/", JoinedGames(tmp_path / "guest.json"))
    guest._window = FakeWindow("http://127.0.0.1:1/")

    for _ in range(60):  # until the measurement lets White through (half of all games)
        host = httpx.post(f"{url}/online/create", json={"color": "black", "fen": FEN}).json()
        game_id = host["game_id"]
        guest._window.url = "http://127.0.0.1:1/"
        guest.join(f"{url}/?join={game_id}")
        opened = guest._window.url
        assert opened.startswith(f"{url}/?game={game_id}#seat=white.")
        token = opened.split("#seat=white.")[1]
        state = httpx.get(f"{url}/state", params={"game_id": game_id}).json()
        assert state["fairness"]["guest_seed"] == guest._joined.seed(url, game_id)

        guest._window.url = f"{url}/?game={game_id}"
        guest._verify_current()
        assert "still running" in guest._window.dialogs[-1]

        for notation, seat_token in (("b4^a6c6", host["token"]), ("a1a8", token)):
            body = {"game_id": game_id, "notation": notation, "token": seat_token}
            state = httpx.post(f"{url}/do_move", json=body).json()["state"]
        if state["winner"]:
            break
    guest._verify_current()
    assert guest._window.dialogs[-1].startswith("Fair. All 1 measurement")


def test_host_is_told_it_rolled_the_dice(host_app, tmp_path):
    app, url = host_app
    desktop = make_desktop(app, url, tmp_path)
    desktop._window.url = f"{url}/?game=whatever"
    desktop._verify_current()
    assert "You hosted this game" in desktop._window.dialogs[-1]


def test_seat_already_taken_opens_as_spectator(host_app, tmp_path):
    app, url = host_app
    host = httpx.post(f"{url}/online/create", json={}).json()
    httpx.post(f"{url}/online/join", json={"game_id": host["game_id"]})
    opened = join_game(f"{url}/?join={host['game_id']}", JoinedGames(tmp_path / "j.json"))
    assert opened == f"{url}/?game={host['game_id']}"


def test_network_guests_cannot_reach_the_hosts_own_games(host_app, tmp_path):
    app, url = host_app
    desktop = make_desktop(app, url, tmp_path)
    lan = "http://127.0.0.1:" + desktop.host().rsplit(":", 1)[1]
    own = httpx.post(f"{url}/init", json={}).json()["game_id"]  # a game against the AI
    for response in (
        httpx.get(f"{lan}/state", params={"game_id": own}),
        httpx.get(f"{lan}/legal_moves", params={"game_id": own}),
        httpx.get(f"{lan}/correlations", params={"game_id": own, "square": "e2"}),
        httpx.post(f"{lan}/do_move", json={"game_id": own, "notation": "e2e4"}),
        httpx.post(f"{lan}/online/join", json={"game_id": own}),
    ):
        assert response.status_code == 404, response.request.url
    assert httpx.get(f"{url}/state", params={"game_id": own}).json()["history"] == []
    for path in ("/docs", "/openapi.json", "/redoc"):
        assert httpx.get(f"{lan}{path}").status_code == 403, path
    assert httpx.get(f"{url}/docs").is_success  # the host keeps them


def test_live_feeds_per_game_are_capped(host_app):
    import asyncio

    import websockets

    from api.server import MAX_FEEDS

    app, url = host_app
    port = free_port("127.0.0.1")
    server = start_server("127.0.0.1", port, GuestsOnly(app))
    game_id = httpx.post(f"{url}/online/create", json={}).json()["game_id"]
    own = httpx.post(f"{url}/init", json={}).json()["game_id"]

    async def check() -> None:
        base = f"ws://127.0.0.1:{port}/ws?game_id="
        feeds = [await websockets.connect(base + game_id) for _ in range(MAX_FEEDS)]
        for feed in feeds:
            await feed.recv()  # the snapshot: subscribed
        extra = await websockets.connect(base + game_id)
        with pytest.raises(websockets.ConnectionClosed) as closed:
            await extra.recv()
        assert closed.value.rcvd.code == 4429
        with pytest.raises(websockets.InvalidStatus):  # refused like an unknown game
            await websockets.connect(base + own)  # the host's own game
        for feed in feeds:
            await feed.close()

    try:
        asyncio.run(check())
    finally:
        stop_server(server)


def test_local_server_answers_only_requests_addressed_to_it():
    app = create_app(ui_dir=None)
    port = free_port("127.0.0.1")
    server = start_server("127.0.0.1", port, LocalOnly(app, port))
    try:
        base = f"http://127.0.0.1:{port}"
        assert httpx.get(f"{base}/health").is_success
        assert httpx.get(f"http://localhost:{port}/health").is_success
        # A page on evil.example whose domain now resolves to 127.0.0.1 (DNS rebinding):
        rebound = httpx.post(f"{base}/init", json={}, headers={"Host": f"evil.example:{port}"})
        assert rebound.status_code == 421
    finally:
        stop_server(server)


def test_pages_can_only_call_the_bridge_methods_meant_for_them():
    public = {name for name in dir(Desktop) if not name.startswith("_")}
    assert public == {"home", "host", "info", "join", "share_online", "stop_hosting"}
