"""Play agents against each other to measure strength.

Each pairing is played twice per seed, once with each colour, and with the same measurement
seed, so luck and the first-move advantage cancel out as far as possible. Games run in
parallel processes.

    python -m agent.arena --games 40 --a iterations=400 --b iterations=100

A game that reaches ``max_plies`` is adjudicated: a material lead of at least
``adjudicate_margin`` pawns counts as a win, anything less as a draw.
"""

from __future__ import annotations

import argparse
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from typing import Any, Optional, Protocol

import numpy as np

from agent.heuristics import evaluate
from agent.mcts import MCTSAgent
from engine.bitboard import BLACK, WHITE
from engine.board import QuantumBoard
from engine.moves import QuantumMove


class Agent(Protocol):
    def choose_move(self, board: QuantumBoard) -> QuantumMove: ...


@dataclass
class GameRecord:
    seed: int
    a_color: int
    winner: Optional[int]  # None for a draw
    reason: str
    plies: int
    a_seconds: float
    b_seconds: float

    @property
    def a_score(self) -> float:
        if self.winner is None:
            return 0.5
        return 1.0 if self.winner == self.a_color else 0.0


def play_game(
    a: Agent,
    b: Agent,
    seed: int,
    a_color: int = WHITE,
    max_plies: int = 200,
    adjudicate_margin: float = 3.0,
) -> GameRecord:
    board = QuantumBoard(rng=np.random.default_rng(seed))
    players = {a_color: a, a_color ^ 1: b}
    seconds = {a_color: 0.0, a_color ^ 1: 0.0}
    while not board.is_over and len(board.history) < max_plies:
        start = time.perf_counter()
        move = players[board.turn].choose_move(board)
        seconds[board.turn] += time.perf_counter() - start
        board.do_move(move)

    plies = len(board.history)
    if board.winner is not None:
        winner, reason = board.winner, "king captured"
    elif board.draw_reason is not None:
        winner, reason = None, board.draw_reason
    else:
        score = evaluate(board, WHITE)
        winner = (
            WHITE if score >= adjudicate_margin else BLACK if -score >= adjudicate_margin else None
        )
        reason = f"adjudicated at {score:+.1f}"
    return GameRecord(seed, a_color, winner, reason, plies, seconds[a_color], seconds[a_color ^ 1])


def _play(args: tuple) -> GameRecord:
    return play_game(*args)


@dataclass
class MatchResult:
    games: list[GameRecord]

    @property
    def score(self) -> float:
        """Agent A's mean score: 1 = won everything, 0.5 = even."""
        return sum(g.a_score for g in self.games) / len(self.games)

    @property
    def elo(self) -> float:
        """Elo difference implied by the score (clipped at 99% to stay finite)."""
        s = min(max(self.score, 0.01), 0.99)
        return -400 * np.log10(1 / s - 1)

    def summary(self) -> str:
        wins = sum(g.a_score == 1 for g in self.games)
        draws = sum(g.a_score == 0.5 for g in self.games)
        losses = len(self.games) - wins - draws
        a_time = sum(g.a_seconds for g in self.games) / sum(g.plies for g in self.games) * 2
        b_time = sum(g.b_seconds for g in self.games) / sum(g.plies for g in self.games) * 2
        return (
            f"A vs B: +{wins} ={draws} -{losses}  score {self.score:.1%}  "
            f"Elo {self.elo:+.0f}  (A {a_time:.2f}s/move, B {b_time:.2f}s/move)"
        )


def match(
    a: Agent,
    b: Agent,
    games: int = 20,
    first_seed: int = 0,
    max_plies: int = 200,
    workers: Optional[int] = None,
) -> MatchResult:
    """Play ``games`` games (rounded up to even) between ``a`` and ``b``, swapping colours."""
    jobs = [
        (a, b, first_seed + i, color, max_plies)
        for i in range((games + 1) // 2)
        for color in (WHITE, BLACK)
    ]
    if workers == 1:
        return MatchResult([_play(job) for job in jobs])
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return MatchResult(list(pool.map(_play, jobs)))


def _agent_from(spec: list[str], seed: int) -> MCTSAgent:
    kwargs: dict[str, Any] = {}
    for item in spec:
        key, value = item.split("=")
        kwargs[key] = float(value) if "." in value else int(value)
    return MCTSAgent(seed=seed, **kwargs)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--games", type=int, default=20)
    parser.add_argument("--max-plies", type=int, default=200)
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--a", nargs="*", default=[], help="MCTSAgent options for A, key=value")
    parser.add_argument("--b", nargs="*", default=[], help="MCTSAgent options for B, key=value")
    args = parser.parse_args()
    result = match(
        _agent_from(args.a, seed=1),
        _agent_from(args.b, seed=2),
        games=args.games,
        max_plies=args.max_plies,
        workers=args.workers,
    )
    for g in result.games:
        color = "wb"[g.a_color]
        print(f"seed {g.seed:3d}  A={color}  A scores {g.a_score}  {g.reason}, {g.plies} plies")
    print(result.summary())


if __name__ == "__main__":
    main()
