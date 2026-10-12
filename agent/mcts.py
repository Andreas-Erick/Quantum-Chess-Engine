"""Monte Carlo Tree Search for quantum chess.

Minimax struggles here: besides the move choice, every measurement branches the game on a
random outcome. This agent uses *open-loop* MCTS: tree nodes stand for sequences of moves,
not for positions. Each iteration replays the sequence on a fresh copy of the root position
with its own random measurement outcomes, so the statistics on each node average over the
quantum dice automatically, weighted by their true probabilities.

Iterations:

1. **Selection**: walk down the tree with UCT, choosing among moves legal in *this* sample.
2. **Expansion**: add one untried move. Quantum chess has a huge branching factor (a queen
   alone has ~200 possible splits), so nodes use *progressive widening*: moves are ordered
   (captures by value first, then ordinary moves interleaved with quantum ones) and a node
   considers only its first ~2*sqrt(visits) candidates.
3. **Simulation**: play a short, capture-biased random rollout, sampling every measurement.
4. **Evaluation & backpropagation**: score the result with the probability-weighted heuristic
   (or 1/0 if a king fell) and update every node on the path.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from agent.heuristics import PIECE_VALUES, win_probability
from engine.bitboard import KING, WHITE
from engine.board import QuantumBoard
from engine.moves import MoveType, QuantumMove


@dataclass
class MoveStats:
    move: QuantumMove
    visits: int
    value: float  # mean reward for the side to move at the root, in [0, 1]


@dataclass
class SearchResult:
    move: QuantumMove
    iterations: int
    elapsed: float
    moves: list[MoveStats] = field(default_factory=list)  # most visited first


class _Node:
    __slots__ = ("children", "visits", "value_sum", "order", "known")

    def __init__(self) -> None:
        self.children: dict[QuantumMove, _Node] = {}
        self.visits = 0
        # Candidate moves in priority order; extended when a new measurement outcome makes
        # moves legal that earlier samples did not see.
        self.order: list[QuantumMove] = []
        self.known: set[QuantumMove] = set()
        # Reward from the point of view of the player who made the move leading here.
        self.value_sum = 0.0


class MCTSAgent:
    def __init__(
        self,
        iterations: int = 400,
        rollout_depth: int = 6,
        exploration: float = 1.4,
        capture_bias: float = 0.5,
        max_group_qubits: int = 12,
        widening: float = 2.0,
        time_limit: Optional[float] = None,
        seed: Optional[int] = None,
    ) -> None:
        """
        Args:
            iterations: maximum number of tree iterations per move.
            rollout_depth: plies of random play before the heuristic takes over.
            exploration: UCT exploration constant.
            capture_bias: probability that a rollout picks a capture when one exists.
            max_group_qubits: stop simulating once an entangled group grows past this size
                and evaluate statically; keeps rollout cost bounded.
            widening: a node with n visits considers its first ``widening * sqrt(n + 1)``
                moves.
            time_limit: optional wall-clock budget in seconds.
            seed: makes the search reproducible.
        """
        self.iterations = iterations
        self.rollout_depth = rollout_depth
        self.exploration = exploration
        self.capture_bias = capture_bias
        self.max_group_qubits = max_group_qubits
        self.widening = widening
        self.time_limit = time_limit
        self.seed = seed

    def choose_move(self, board: QuantumBoard) -> QuantumMove:
        return self.search(board).move

    def search(self, board: QuantumBoard) -> SearchResult:
        if board.winner is not None:
            raise ValueError("the game is over")
        root_moves = board.legal_moves()
        if not root_moves:
            raise ValueError("no legal moves")

        rng = random.Random(self.seed)
        np_rng = np.random.default_rng(self.seed)
        root = _Node()
        start = time.perf_counter()
        iterations = 0

        winning = self._immediate_win(board, root_moves)
        if winning is not None:
            return SearchResult(
                winning, 0, time.perf_counter() - start, [MoveStats(winning, 0, 1.0)]
            )

        while iterations < self.iterations:
            if self.time_limit is not None and time.perf_counter() - start > self.time_limit:
                break
            self._iterate(board.copy(rng=np_rng), root, rng)
            iterations += 1

        stats = sorted(
            (MoveStats(m, n.visits, n.value_sum / n.visits) for m, n in root.children.items()),
            key=lambda s: (s.visits, s.value),
            reverse=True,
        )
        best = stats[0].move if stats else rng.choice(root_moves)
        return SearchResult(best, iterations, time.perf_counter() - start, stats)

    # --- One iteration --------------------------------------------------------------

    def _iterate(self, sim: QuantumBoard, root: _Node, rng: random.Random) -> None:
        path: list[tuple[_Node, int]] = []  # (node, player who moved into it)
        node = root
        while sim.winner is None and not self._too_entangled(sim):
            legal = sim.legal_moves()
            if not legal:
                break
            candidates = self._candidates(node, sim, legal, rng)
            untried = [m for m in candidates if m not in node.children]
            mover = sim.turn
            if untried:
                move = untried[0]
                child = node.children[move] = _Node()
                sim.do_move(move)
                path.append((child, mover))
                break
            move = self._select(node, candidates)
            sim.do_move(move)
            node = node.children[move]
            path.append((node, mover))

        reward_white = self._rollout(sim, rng)
        root.visits += 1
        for visited, mover in path:
            visited.visits += 1
            visited.value_sum += reward_white if mover == WHITE else 1.0 - reward_white

    def _candidates(
        self, node: _Node, sim: QuantumBoard, legal: list[QuantumMove], rng: random.Random
    ) -> list[QuantumMove]:
        new = [m for m in legal if m not in node.known]
        if new:
            node.order.extend(self._order_moves(sim, new, rng))
            node.known.update(new)
        width = max(1, math.ceil(self.widening * math.sqrt(node.visits + 1)))
        legal_set = set(legal)
        return [m for m in node.order if m in legal_set][:width]

    @staticmethod
    def _order_moves(
        sim: QuantumBoard, moves: list[QuantumMove], rng: random.Random
    ) -> list[QuantumMove]:
        """Captures by expected value, then ordinary and quantum moves interleaved 2:1."""
        captures: list[tuple[float, QuantumMove]] = []
        jumps: list[QuantumMove] = []
        quantum: list[QuantumMove] = []
        for move in moves:
            if move.move_type is not MoveType.JUMP:
                quantum.append(move)
                continue
            target = sim.piece_at(move.target)
            if target is not None and target.color != sim.turn:
                value = 100.0 if target.kind == KING else PIECE_VALUES[target.kind]
                captures.append((value * sim.probability(move.target), move))
            else:
                jumps.append(move)
        rng.shuffle(jumps)
        rng.shuffle(quantum)
        ordered = [m for _, m in sorted(captures, key=lambda c: -c[0])]
        while jumps or quantum:
            ordered.extend(jumps[:2])
            ordered.extend(quantum[:1])
            del jumps[:2], quantum[:1]
        return ordered

    def _select(self, node: _Node, legal: list[QuantumMove]) -> QuantumMove:
        log_parent = math.log(max(node.visits, 1))

        def uct(move: QuantumMove) -> float:
            child = node.children[move]
            exploit = child.value_sum / child.visits if child.visits else 0.5
            return exploit + self.exploration * math.sqrt(log_parent / (child.visits + 1))

        return max(legal, key=uct)

    def _rollout(self, sim: QuantumBoard, rng: random.Random) -> float:
        for _ in range(self.rollout_depth):
            if sim.winner is not None or self._too_entangled(sim):
                break
            legal = sim.legal_moves()
            if not legal:
                break
            sim.do_move(self._rollout_move(sim, legal, rng))
        return win_probability(sim, WHITE)

    def _rollout_move(
        self, sim: QuantumBoard, legal: list[QuantumMove], rng: random.Random
    ) -> QuantumMove:
        captures = []
        for move in legal:
            if move.move_type is not MoveType.JUMP:
                continue
            target = sim.piece_at(move.target)
            if target is not None and target.color != sim.turn:
                if target.kind == KING:
                    return move
                captures.append(move)
        if captures and rng.random() < self.capture_bias:
            return rng.choice(captures)
        return rng.choice(legal)

    def _too_entangled(self, sim: QuantumBoard) -> bool:
        return sim.register.largest_group > self.max_group_qubits

    @staticmethod
    def _immediate_win(board: QuantumBoard, moves: list[QuantumMove]) -> Optional[QuantumMove]:
        """A capture of the enemy king that succeeds with certainty, if there is one."""
        for move in moves:
            if move.move_type is not MoveType.JUMP:
                continue
            target = board.piece_at(move.target)
            if target is None or target.kind != KING or target.color == board.turn:
                continue
            trial = board.copy()
            if trial.do_move(move).winner == board.turn and not trial.history[-1].measurements:
                return move
        return None
