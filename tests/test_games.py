"""The Game module on its own, without HTTP: turns, seats, dice and live feeds."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from agent.mcts import MCTSAgent
from api.fairness import SeededDice
from api.games import (
    MAX_FEEDS,
    BadMove,
    GameOver,
    GameStore,
    NoAiOnline,
    NotOnline,
    NotYourTurn,
    SeatsTaken,
    UnknownGame,
    WaitingForOpponent,
)
from api.server import GUEST, create_app
from engine.board import QuantumBoard


class FakeLoop:
    """Stands in for a feed's event loop: delivers at once, in order."""

    def call_soon_threadsafe(self, callback, *args):
        callback(*args)


def feed():
    return (FakeLoop(), asyncio.Queue())


def online_game(store=None):
    store = store or GameStore()
    game = store.create(QuantumBoard(), online=True)
    host = game.seat_host("white")
    return game, host


def test_moves_wait_for_the_friend_then_follow_the_turn():
    game, host = online_game()
    with pytest.raises(WaitingForOpponent):
        game.play("e2e4", host.token)
    guest = game.join("seed")
    assert guest.color == "black"
    with pytest.raises(NotYourTurn):
        game.play("e2e4", guest.token)
    with pytest.raises(NotYourTurn):
        game.play("e2e4", None)
    game.play("e2e4", host.token)
    with pytest.raises(NotYourTurn):
        game.play("e7e5", host.token)
    game.play("e7e5", guest.token)


def test_two_seats_only():
    game, host = online_game()
    with pytest.raises(SeatsTaken):
        game.seat_host("white")
    game.join()
    with pytest.raises(SeatsTaken):
        game.join()


def test_local_games_have_no_seats_and_no_dice_to_join():
    game = GameStore().create(QuantumBoard())
    with pytest.raises(NotOnline):
        game.join()
    with pytest.raises(NotOnline):
        game.seat_host("white")
    assert game.state().seats is None and game.state().fairness is None


def test_joining_seeds_the_dice_with_both_shares():
    game, host = online_game()
    guest = game.join("guest-seed")
    secret = game._secret  # the server's share, revealed only at the end
    game.play("g1^f3h3", host.token)
    game.play("e7e5", guest.token)
    response = game.play("f3e5", host.token)  # captures, measuring the knight on f3
    expected = SeededDice(secret, "guest-seed").random() < 0.5
    assert response.measurements[0].outcome == expected


def test_feeds_see_joins_and_moves_in_order():
    game, host = online_game()
    loop, queue = feed()
    first = game.subscribe((loop, queue))
    assert first["type"] == "state"
    guest = game.join()
    game.play("e2e4", host.token)
    game.play("e7e5", guest.token)
    messages = [queue.get_nowait() for _ in range(queue.qsize())]
    assert [m["type"] for m in messages] == ["state", "move", "move"]
    assert [m["move"] for m in messages[1:]] == ["e2e4", "e7e5"]
    game.unsubscribe((loop, queue))
    assert game.feed_count == 0


def test_feeds_are_capped():
    game = GameStore().create(QuantumBoard())
    for _ in range(MAX_FEEDS):
        assert game.subscribe(feed()) is not None
    assert game.subscribe(feed()) is None


def test_bad_and_late_moves():
    game = GameStore().create(QuantumBoard("4k3/8/8/8/8/8/8/4K2R w - - 0 1"))
    with pytest.raises(BadMove):
        game.play("e2e4")
    game.play("h1h8")
    game.play("e8e7")
    game.play("h8h7")
    game.play("e7f6")
    with pytest.raises(BadMove):
        game.play("zz")
    game = GameStore().create(QuantumBoard("4k3/4R3/8/8/8/8/8/4K3 w - - 0 1"))
    game.play("e7e8")  # captures the king
    with pytest.raises(GameOver):
        game.play("e1e2")


def test_no_ai_in_online_games():
    game, _ = online_game()
    with pytest.raises(NoAiOnline):
        game.play_ai(MCTSAgent(iterations=5, seed=0))


def test_guests_see_only_online_games():
    store = GameStore()
    local = store.create(QuantumBoard())
    online, _ = online_game(store)
    assert store.get(online.id, guest=True) is online
    assert store.get(local.id) is local
    with pytest.raises(UnknownGame):
        store.get(local.id, guest=True)
    with pytest.raises(UnknownGame):
        store.get("nope")


# --- The API's own guest policy, without the desktop app ------------------------------


def as_guest(app):
    async def guest_app(scope, receive, send):
        await app({**scope, GUEST: True}, receive, send)

    return guest_app


def test_the_api_refuses_guests_what_only_the_host_may_do():
    store = GameStore()
    host = TestClient(create_app(store, ui_dir=None))
    guest = TestClient(as_guest(create_app(store, ui_dir=None)))
    local = host.post("/init").json()["game_id"]
    online = host.post("/online/create", json={}).json()["game_id"]
    for path in ("/init", "/ai_move", "/online/create"):
        assert guest.post(path, json={"game_id": online}).status_code == 403, path
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert guest.get(path).status_code == 403, path
    assert guest.get("/state", params={"game_id": local}).status_code == 404
    assert guest.post("/online/join", json={"game_id": online}).is_success
    assert host.get("/docs").is_success
