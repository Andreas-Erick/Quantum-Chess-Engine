"""Phase 4: the REST API and the JSON contract."""

import pytest
from fastapi.testclient import TestClient

from agent.client import board_from_state, play
from agent.mcts import MCTSAgent
from api.server import create_app

KNIGHT_FEN = "4k3/8/8/4b3/8/8/8/1N2K3 w - - 0 1"


@pytest.fixture
def client():
    return TestClient(create_app())


def new_game(client, **body) -> dict:
    response = client.post("/init", json=body)
    assert response.status_code == 200
    return response.json()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_init_returns_classical_start(client):
    state = new_game(client)
    assert len(state["probabilities"]) == 64
    assert sum(state["probabilities"]) == 32
    assert state["turn"] == "white" and state["winner"] is None
    assert state["entanglement_groups"] == [] and state["history"] == []
    assert {
        "square": "e1",
        "symbol": "K",
        "kind": "king",
        "color": "white",
        "probability": 1.0,
    } in (state["pieces"])


def test_init_without_body(client):
    assert client.post("/init").status_code == 200


def test_init_rejects_bad_fen(client):
    assert client.post("/init", json={"fen": "nonsense"}).status_code == 400


def test_split_via_structured_payload(client):
    game_id = new_game(client)["game_id"]
    response = client.post(
        "/do_move",
        json={
            "game_id": game_id,
            "move_type": "split",
            "source": "g1",
            "target1": "f3",
            "target2": "h3",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["move"] == "g1^f3h3" and body["executed"]
    probs = body["state"]["probabilities"]
    assert probs[21] == pytest.approx(0.5) and probs[23] == pytest.approx(0.5)  # f3, h3
    assert probs[6] == 0  # g1
    assert sorted(body["state"]["entanglement_groups"][0]) == ["f3", "h3"]


def test_move_via_notation_and_state(client):
    game_id = new_game(client)["game_id"]
    client.post("/do_move", json={"game_id": game_id, "notation": "e2e4"})
    state = client.get("/state", params={"game_id": game_id}).json()
    assert state["turn"] == "black"
    assert state["history"] == [{"notation": "e2e4", "executed": True, "outcomes": []}]


def test_measurement_is_reported(client):
    game_id = new_game(client, fen=KNIGHT_FEN, seed=3)["game_id"]
    client.post("/do_move", json={"game_id": game_id, "notation": "b1^a3c3"})
    body = client.post("/do_move", json={"game_id": game_id, "notation": "e5c3"}).json()
    [m] = body["measurements"]
    assert m["kind"] == "square" and m["squares"] == ["c3"]
    assert m["probability"] == pytest.approx(0.5)
    assert set(m["collapsed"]) == {"a3", "c3"}
    assert (body["captured"] == "N") == m["outcome"]
    assert body["state"]["history"][-1]["outcomes"] == [m["outcome"]]


@pytest.mark.parametrize(
    "payload",
    [
        {"notation": "e2e5"},  # illegal
        {"notation": "zz"},  # unparseable
        {"move_type": "split", "source": "g1", "target1": "f3"},  # missing target2
    ],
)
def test_bad_moves_are_rejected(client, payload):
    game_id = new_game(client)["game_id"]
    response = client.post("/do_move", json={"game_id": game_id, **payload})
    assert response.status_code in (400, 422)
    assert client.get("/state", params={"game_id": game_id}).json()["turn"] == "white"


def test_unknown_game(client):
    assert client.get("/state", params={"game_id": "nope"}).status_code == 404
    assert client.post("/do_move", json={"game_id": "nope", "notation": "e2e4"}).status_code == 404


def test_legal_moves(client):
    game_id = new_game(client)["game_id"]
    moves = client.get("/legal_moves", params={"game_id": game_id}).json()["moves"]
    assert "e2e4" in moves and "g1^f3h3" in moves


def test_moves_after_game_over_conflict(client):
    game_id = new_game(client, fen="4k3/8/8/8/8/8/8/4KQ2 w - - 0 1")["game_id"]
    for move in ["f1f8", "e8e7", "f8e7"]:
        client.post("/do_move", json={"game_id": game_id, "notation": move})
    assert client.get("/state", params={"game_id": game_id}).json()["winner"] == "white"
    assert client.post("/do_move", json={"game_id": game_id, "notation": "e1e2"}).status_code == 409


def test_ai_move(client):
    game_id = new_game(client, fen="4k3/8/8/3q4/8/8/8/3RK3 w - - 0 1", seed=0)["game_id"]
    response = client.post("/ai_move", json={"game_id": game_id, "iterations": 200, "seed": 0})
    assert response.status_code == 200
    body = response.json()
    assert body["move"] == "d1d5" and body["captured"] == "q"
    assert body["search"]["iterations"] == 200
    assert body["search"]["top_moves"][0]["move"] == "d1d5"


def test_state_json_replays_to_identical_board(client):
    game_id = new_game(client, seed=11)["game_id"]
    for move in ["g1^f3h3", "b8^a6c6", "f3e5", "c6e5", "h3g5", "a6b4"]:
        client.post("/do_move", json={"game_id": game_id, "notation": move})
    state = client.get("/state", params={"game_id": game_id}).json()
    board = board_from_state(state)
    assert board.probabilities() == pytest.approx(state["probabilities"])
    assert board.turn == (0 if state["turn"] == "white" else 1)


def test_remote_agent_self_play_through_api(client):
    agent = MCTSAgent(iterations=20, rollout_depth=2, seed=5)
    final = play(client, agent, color="both", max_moves=12, log=lambda *_: None)
    assert len(final["history"]) == 12 or final["winner"] is not None
    # Every move the client made went through the API and replays consistently.
    assert board_from_state(final).probabilities() == pytest.approx(final["probabilities"])
