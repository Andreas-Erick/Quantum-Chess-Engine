"""Play through the REST API as an independent process.

The agent sees only JSON. It rebuilds the exact quantum state by replaying the game history
(moves plus recorded measurement outcomes), searches locally, and posts its move.

    python -m agent.client --url http://localhost:8000 --color both      # self-play
    python -m agent.client --url http://localhost:8000 --game-id ID --color black
"""

from __future__ import annotations

import argparse
import time
from typing import Optional

import httpx

from agent.mcts import MCTSAgent
from engine.board import QuantumBoard


def board_from_state(state: dict) -> QuantumBoard:
    records = [(h["notation"], h["outcomes"]) for h in state["history"]]
    return QuantumBoard.replay(state["initial_fen"], records)


def play(
    client: httpx.Client,
    agent: MCTSAgent,
    game_id: Optional[str] = None,
    color: str = "both",
    max_moves: int = 200,
    poll_interval: float = 0.5,
    log=print,
) -> dict:
    """Play ``color`` ("white", "black" or "both") until the game ends; return the final state."""
    if game_id is None:
        response = client.post("/init", json={})
        response.raise_for_status()
        game_id = response.json()["game_id"]
        log(f"created game {game_id}")

    for _ in range(max_moves):
        state = client.get("/state", params={"game_id": game_id}).raise_for_status().json()
        if state["winner"] is not None:
            break
        if color != "both" and state["turn"] != color:
            time.sleep(poll_interval)
            continue
        move = agent.choose_move(board_from_state(state))
        response = client.post("/do_move", json={"game_id": game_id, "notation": move.notation()})
        body = response.raise_for_status().json()
        status = "" if body["executed"] else "  (failed after measurement)"
        captured = f"  x{body['captured']}" if body["captured"] else ""
        log(f"{state['turn']:>5}: {body['move']}{captured}{status}")
    else:
        state = client.get("/state", params={"game_id": game_id}).raise_for_status().json()

    log(f"winner: {state['winner'] or 'none (move limit)'}")
    return state


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--game-id")
    parser.add_argument("--color", choices=["white", "black", "both"], default="both")
    parser.add_argument("--iterations", type=int, default=300)
    parser.add_argument("--max-moves", type=int, default=200)
    parser.add_argument("--seed", type=int)
    args = parser.parse_args()

    agent = MCTSAgent(iterations=args.iterations, seed=args.seed)
    with httpx.Client(base_url=args.url, timeout=60) as client:
        play(client, agent, args.game_id, args.color, args.max_moves)


if __name__ == "__main__":
    main()
