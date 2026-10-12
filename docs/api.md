# API reference

The server is a FastAPI app (`api/server.py`). Its request and response models are in
`api/schemas.py`. A running server also serves interactive docs at `/docs` and the OpenAPI schema
at `/openapi.json`. Both are refused to guests of a desktop app's hosting listener.

For how the server fits with the engine and the UI, see [architecture.md](architecture.md).

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/init` | New game (`{fen?, seed?}`) → `GameState` |
| `POST` | `/do_move` | `{game_id, notation, token?}` or `{game_id, move_type, source, target1, target2?, source2?, promotion?, token?}` → `MoveResponse` |
| `GET` | `/state?game_id=` | Pieces, 64 probabilities, entanglement groups, full history → `GameState` |
| `GET` | `/legal_moves?game_id=` | All legal moves in notation |
| `GET` | `/levels` | AI strength levels (`easy`, `medium`, `hard`) and which is the default |
| `GET` | `/correlations?game_id=&square=` | Entangled squares' probabilities if that square is occupied / empty |
| `POST` | `/ai_move` | MCTS move (`{game_id, level?}` or `{game_id, iterations?, rollout_depth?, time_limit?, seed?}`) → `MoveResponse` + `search` |
| `POST` | `/online/create` | Online game (`{color: white\|black\|random, fen?}`) → `{game_id, color, token, state}` |
| `POST` | `/online/join` | Take the open seat (`{game_id, seed?}`) → `{game_id, color, token, state}` |
| `WS` | `/ws?game_id=` | Live feed (see below) |
| `GET` | `/health` | Liveness probe |

Move notation: `e2e4` (jump), `e7e8q` (promotion), `b1^a3c3` (split), `a3c3^b1` (merge).

## Responses

- **`GameState`**: `game_id`, `turn`, `winner`, `draw_reason`, `check` (possible king squares
  the opponent could capture, with probabilities), `probabilities` (64 values, a1 … h8),
  `pieces`, `entanglement_groups`, `history` (each move's notation, whether it executed, and its
  measurement outcomes), `seats` (online games).
- **Online games** also carry `fairness`: the server's `commitment`, the joiner's `guest_seed`,
  and the `secret` once the game is over.
- **`MoveResponse`**: the `move`, whether it `executed`, what was `captured`, the `measurements`
  (what was asked, the prior probability, the outcome, every square that collapsed), and the new
  `state`.

## Live feed

`/ws?game_id=` sends `{"type": "state", "state": GameState}` on connect and when a player joins,
and `{"type": "move", ...MoveResponse}` after every move. Anything the client sends is ignored;
it only keeps the connection alive. Close codes: `4404` unknown game, `4429` too many feeds for
the game (16).

## Errors

| Status | Meaning |
|---|---|
| `400` | Illegal move or bad FEN |
| `403` | Not your turn in an online game, an AI move requested in an online game, or a host-only endpoint on a desktop app's hosting listener |
| `404` | Unknown game (guests also get it for the host's own games) |
| `409` | Game over, or the opponent isn't seated yet, or both seats are taken |
| `422` | Malformed payload, including over-long ids, tokens, FENs or moves |

## Guests of a desktop app

When the desktop app hosts, other machines reach the same app through a second listener (on the
network, or through an internet link). Guests can join, watch and play the host's **online**
games: `/state`, `/legal_moves`, `/correlations`, `/do_move`, `/online/join` and `/ws` work for
those. `/init`, `/ai_move`, `/online/create` and the docs return `403`, and the host's other games
don't exist for them (`404`).

## Using the engine from Python

```python
from engine.board import QuantumBoard

board = QuantumBoard()
board.do_move("g1^f3h3")            # knight: 50% f3, 50% h3
board.do_move("e7e5")
board.do_move("f3h3^g1")            # interference: back on g1 with certainty
print(board)
print(board.probabilities())        # 64 occupancy probabilities, a1..h8
```

## AI self-play through the API

```bash
python -m agent.client --url http://localhost:8000 --color both                 # self-play
python -m agent.client --url http://localhost:8000 --game-id ID --color black   # join a game
python -m agent.client --level hard --color white                               # pick a level
docker compose --profile demo up --build                                        # API + self-play
```
