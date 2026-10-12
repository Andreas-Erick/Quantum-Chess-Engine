"""Online play: seats, turn enforcement and the live WebSocket feed."""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from api.server import GameStore, create_app


@pytest.fixture
def client():
    return TestClient(create_app())


def create(client, **body) -> dict:
    response = client.post("/online/create", json=body)
    assert response.status_code == 200
    return response.json()


def join(client, game_id: str) -> dict:
    response = client.post("/online/join", json={"game_id": game_id})
    assert response.status_code == 200
    return response.json()


def move(client, game_id: str, notation: str, token=None):
    return client.post("/do_move", json={"game_id": game_id, "notation": notation, "token": token})


def test_create_claims_one_seat(client):
    seat = create(client, color="black")
    assert seat["color"] == "black" and len(seat["token"]) >= 16
    assert seat["state"]["seats"] == {"white": False, "black": True}


def test_random_color_is_a_real_color(client):
    assert create(client, color="random")["color"] in ("white", "black")


def test_local_games_have_no_seats(client):
    assert client.post("/init").json()["seats"] is None


def test_join_takes_the_open_seat_then_the_game_is_full(client):
    host = create(client, color="white")
    guest = join(client, host["game_id"])
    assert guest["color"] == "black" and guest["token"] != host["token"]
    assert guest["state"]["seats"] == {"white": True, "black": True}
    assert client.post("/online/join", json={"game_id": host["game_id"]}).status_code == 409


def test_join_rejects_local_and_unknown_games(client):
    local = client.post("/init").json()["game_id"]
    assert client.post("/online/join", json={"game_id": local}).status_code == 400
    assert client.post("/online/join", json={"game_id": "nope"}).status_code == 404


def test_only_the_side_to_move_may_move(client):
    host = create(client, color="white")
    guest = join(client, host["game_id"])
    game_id = host["game_id"]
    assert move(client, game_id, "e2e4").status_code == 403  # no token
    assert move(client, game_id, "e2e4", guest["token"]).status_code == 403  # black's token
    assert move(client, game_id, "e2e4", "forged").status_code == 403
    assert move(client, game_id, "e2e4", host["token"]).status_code == 200
    assert move(client, game_id, "e7e5", host["token"]).status_code == 403  # now black's turn
    assert move(client, game_id, "e7e5", guest["token"]).status_code == 200


def test_no_moves_until_both_players_are_seated(client):
    host = create(client, color="white")
    assert move(client, host["game_id"], "e2e4", host["token"]).status_code == 409


def test_no_ai_in_online_games(client):
    host = create(client)
    response = client.post("/ai_move", json={"game_id": host["game_id"], "level": "easy"})
    assert response.status_code == 403


def test_tokens_never_appear_in_public_state(client):
    host = create(client)
    state = client.get("/state", params={"game_id": host["game_id"]}).text
    assert host["token"] not in state


def test_live_feed_sends_state_then_joins_and_moves(client):
    host = create(client, color="white")
    game_id = host["game_id"]
    with client.websocket_connect(f"/ws?game_id={game_id}") as feed:
        first = feed.receive_json()
        assert first["type"] == "state" and first["state"]["seats"]["black"] is False

        guest = join(client, game_id)
        joined = feed.receive_json()
        assert joined["type"] == "state" and joined["state"]["seats"]["black"] is True

        move(client, game_id, "g1^f3h3", host["token"])
        update = feed.receive_json()
        assert update["type"] == "move" and update["move"] == "g1^f3h3"
        assert update["state"]["turn"] == "black"
        assert update["state"]["probabilities"][21] == pytest.approx(0.5)

        move(client, game_id, "e7e5", guest["token"])
        assert feed.receive_json()["state"]["history"][-1]["notation"] == "e7e5"


def test_live_feed_also_follows_local_games(client):
    game_id = client.post("/init").json()["game_id"]
    with client.websocket_connect(f"/ws?game_id={game_id}") as feed:
        feed.receive_json()
        client.post("/do_move", json={"game_id": game_id, "notation": "e2e4"})
        assert feed.receive_json()["move"] == "e2e4"


def test_live_feed_unsubscribes_on_disconnect():
    store = GameStore()
    client = TestClient(create_app(store))
    game_id = client.post("/init").json()["game_id"]
    with client.websocket_connect(f"/ws?game_id={game_id}") as feed:
        feed.receive_json()
        assert len(store.get(game_id).subscribers) == 1
    assert store.get(game_id).subscribers == []
    assert client.post("/do_move", json={"game_id": game_id, "notation": "e2e4"}).status_code == 200


def test_live_feed_for_unknown_game_is_refused(client):
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect("/ws?game_id=nope") as feed:
            feed.receive_json()
    assert excinfo.value.code == 4404


def test_store_forgets_the_least_recently_used_game():
    store = GameStore(max_games=3)
    client = TestClient(create_app(store))
    first, second, third = (client.post("/init").json()["game_id"] for _ in range(3))
    client.get("/state", params={"game_id": first})  # keeps it fresh
    client.post("/init")
    assert client.get("/state", params={"game_id": second}).status_code == 404
    for game_id in (first, third):
        assert client.get("/state", params={"game_id": game_id}).is_success


def test_oversized_fields_are_refused(client):
    assert client.post("/init", json={"fen": "8/" * 200}).status_code == 422
    game_id = client.post("/init").json()["game_id"]
    body = {"game_id": game_id, "notation": "e2e4" * 100}
    assert client.post("/do_move", json=body).status_code == 422
