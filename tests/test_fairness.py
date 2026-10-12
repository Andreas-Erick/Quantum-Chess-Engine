"""Fair dice in online games: commit, seed, reveal, verify."""

import copy

import httpx
import pytest
from fastapi.testclient import TestClient

from api.fairness import SeededDice, commitment, main, verify
from api.server import create_app
from desktop.app import free_port, start_server

# Black splits a knight across the a-file; White's rook then tries to slide to the king on a8,
# which measures whether the path is clear. If it is, White captures the king and wins.
FEN = "k7/8/8/8/1n6/8/8/R3K3 b - - 0 1"


@pytest.fixture
def client():
    return TestClient(create_app())


def finished_game(client) -> dict:
    """Play the position above until the measurement lets White win (half of all games)."""
    for attempt in range(60):
        host = client.post("/online/create", json={"color": "black", "fen": FEN}).json()
        game_id = host["game_id"]
        guest = client.post(
            "/online/join", json={"game_id": game_id, "seed": f"guest-{attempt}"}
        ).json()
        client.post(
            "/do_move", json={"game_id": game_id, "notation": "b4^a6c6", "token": host["token"]}
        )
        response = client.post(
            "/do_move", json={"game_id": game_id, "notation": "a1a8", "token": guest["token"]}
        ).json()
        assert response["measurements"], "the slide must measure the path"
        if response["state"]["winner"]:
            return response["state"]
    raise AssertionError("the rook never got through")


def test_dice_are_deterministic_uniform_and_seed_dependent():
    a, b = SeededDice("s", "g"), SeededDice("s", "g")
    rolls = [a.random() for _ in range(2000)]
    assert rolls == [b.random() for _ in range(2000)]
    assert all(0 <= r < 1 for r in rolls) and 0.45 < sum(rolls) / len(rolls) < 0.55
    assert SeededDice("s", "h").random() != rolls[0]


def test_commitment_published_secret_hidden_until_the_end(client):
    host = client.post("/online/create", json={}).json()
    fairness = host["state"]["fairness"]
    assert len(fairness["commitment"]) == 64
    assert fairness["guest_seed"] is None and fairness["secret"] is None

    joined = client.post("/online/join", json={"game_id": host["game_id"], "seed": "abc"}).json()
    assert joined["state"]["fairness"]["guest_seed"] == "abc"
    assert joined["state"]["fairness"]["secret"] is None
    assert joined["state"]["fairness"]["commitment"] == fairness["commitment"]


def test_joiner_without_seed_gets_one(client):
    host = client.post("/online/create", json={}).json()
    joined = client.post("/online/join", json={"game_id": host["game_id"]}).json()
    assert len(joined["state"]["fairness"]["guest_seed"]) == 64


def test_local_games_have_no_fairness_info(client):
    assert client.post("/init").json()["fairness"] is None


def test_finished_game_reveals_secret_and_verifies(client):
    state = finished_game(client)
    secret = state["fairness"]["secret"]
    assert secret and commitment(secret) == state["fairness"]["commitment"]
    verdict = verify(state, state["fairness"]["guest_seed"])
    assert verdict.fair, verdict.reason
    assert "All 1 measurement outcomes match the dice" in verdict.reason
    assert "can't rule out" in verify(state).reason  # fair, with a caveat


def test_tampering_is_detected(client):
    state = finished_game(client)

    flipped = copy.deepcopy(state)
    flipped["history"][-1]["outcomes"] = [not o for o in flipped["history"][-1]["outcomes"]]
    assert not verify(flipped).fair

    swapped = copy.deepcopy(state)
    swapped["fairness"]["secret"] = "0" * 64
    assert "commitment" in verify(swapped).reason

    # A server swapping in its own seed is caught by the joiner's copy of theirs.
    mine = state["fairness"]["guest_seed"]
    reseeded = copy.deepcopy(state)
    reseeded["fairness"]["guest_seed"] = "chosen-by-the-host"
    assert (
        verify(reseeded, mine).reason == "The server used a different seed from the one you sent."
    )


def test_unfinished_and_local_games_are_not_verified(client):
    host = client.post("/online/create", json={}).json()
    assert verify(host["state"]).reason == "Nobody has joined this game yet."
    assert not verify(client.post("/init").json()).fair


def test_command_line_checks_a_live_server(capsys):
    port = free_port("127.0.0.1")
    server = start_server("127.0.0.1", port, ui_dir=None)
    try:
        state = finished_game(httpx.Client(base_url=f"http://127.0.0.1:{port}"))
        with pytest.raises(SystemExit) as exit_info:
            main(
                [
                    f"http://127.0.0.1:{port}/?game={state['game_id']}",
                    "--seed",
                    state["fairness"]["guest_seed"],
                ]
            )
        assert exit_info.value.code == 0
        assert capsys.readouterr().out.startswith("FAIR:")
    finally:
        server.should_exit = True
