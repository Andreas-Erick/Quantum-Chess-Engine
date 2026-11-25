"""validate and legal_moves are one definition of legality, and replay checks a whole game."""

import random

import numpy as np
import pytest

from engine.bitboard import (
    KING_ATTACKS,
    KNIGHT_ATTACKS,
    QUEEN,
    bishop_attacks,
    iter_squares,
    rook_attacks,
)
from engine.bitboard import parse_square as sq
from engine.board import IllegalMoveError, QuantumBoard, ReplayError
from engine.classical import PROMOTION_PIECES, Piece
from engine.moves import Jump, Merge, QuantumMove, Split


def candidates(board: QuantumBoard) -> set[QuantumMove]:
    """Every move of any shape the side to move might try: a superset of the legal ones."""
    moves: set[QuantumMove] = set()
    own = [s for s, p in enumerate(board.labels) if p is not None and p.color == board.turn]
    for src in own:
        for dst in range(64):
            moves.add(Jump(src, dst))
            moves.update(Jump(src, dst, p) for p in PROMOTION_PIECES)
        lines = bishop_attacks(src, 0) | rook_attacks(src, 0)
        near = list(iter_squares(lines | KNIGHT_ATTACKS[src] | KING_ATTACKS[src]))
        moves.update(Split(src, a, b) for a in near for b in near if a != b)
    for a in own:
        for b in own:
            if a != b and board.labels[a] == board.labels[b]:
                moves.update(Merge(a, b, t) for t in range(64))
    return moves


def unordered(move: QuantumMove) -> tuple:
    """legal_moves lists each split and merge once, in one order of its two squares; validate
    accepts both orders."""
    if isinstance(move, Split):
        return ("split", move.source, frozenset(move.targets))
    if isinstance(move, Merge):
        return ("merge", frozenset(move.sources), move.target)
    return ("jump", move)


def is_valid(board: QuantumBoard, move: QuantumMove) -> bool:
    try:
        board.validate(move)
    except IllegalMoveError:
        return False
    return True


@pytest.mark.parametrize("seed", range(4))
def test_validate_accepts_exactly_the_legal_moves(seed):
    chooser = random.Random(seed)
    board = QuantumBoard(rng=np.random.default_rng(seed))
    for _ in range(14):
        legal = board.legal_moves()
        if not legal or board.register.largest_group > 8:
            break
        valid = {unordered(m) for m in candidates(board) if is_valid(board, m)}
        assert valid == {unordered(m) for m in legal}
        assert len({unordered(m) for m in legal}) == len(legal)  # each move listed once
        # Lean towards quantum moves, so merges and splits of split pieces come up.
        quantum = [m for m in legal if not isinstance(m, Jump)]
        board.do_move(chooser.choice(quantum if quantum and chooser.random() < 0.6 else legal))


def test_bare_promotion_is_shorthand_for_a_queen():
    board = QuantumBoard("4k3/P7/8/8/8/8/8/4K3 w - - 0 1")
    assert not is_valid(board, Jump(sq("a7"), sq("a8")))  # not in legal_moves either
    result = board.do_move("a7a8")
    assert result.move == Jump(sq("a7"), sq("a8"), QUEEN)
    assert board.history[-1].move.notation() == "a7a8q"
    assert board.piece_at(sq("a8")) == Piece(0, QUEEN)


def test_promotion_only_on_the_last_rank():
    board = QuantumBoard("4k3/8/P7/8/8/8/8/4K3 w - - 0 1")
    with pytest.raises(IllegalMoveError):
        board.do_move("a6a7q")


def test_replay_names_the_first_move_that_differs():
    with pytest.raises(ReplayError) as error:
        QuantumBoard.replay(
            "4k3/8/8/8/8/8/8/1N2K3 w - - 0 1", [("b1^a3c3", []), ("e8d8", []), ("c3c3", [])]
        )
    assert error.value.ply == 3 and error.value.notation == "c3c3"


def test_replay_checks_whether_moves_executed():
    board = QuantumBoard("4k3/8/8/8/8/8/8/1N2K3 w - - 0 1", rng=np.random.default_rng(0))
    for move in ("b1^a3c3", "e8d8", "c3e4"):
        board.do_move(move)
    records = [(r.move.notation(), r.outcomes, r.executed) for r in board.history]
    QuantumBoard.replay(board.initial_fen, records)
    notation, outcomes, executed = records[-1]
    with pytest.raises(ReplayError, match="executed"):
        QuantumBoard.replay(board.initial_fen, [*records[:-1], (notation, outcomes, not executed)])


class Always:
    def __init__(self, value: float) -> None:
        self.value = value

    def random(self) -> float:
        return self.value


def test_replay_with_dice_rolls_instead_of_forcing():
    # The knight splits, then captures the pawn on e5 from f3, which measures it.
    fen = "4k3/8/8/4p3/8/8/8/4K1N1 w - - 0 1"
    records = [("g1^f3h3", []), ("e8d8", []), ("f3e5", [True])]
    board = QuantumBoard.replay(fen, records, Always(0.0), check_dice=True)
    assert board.piece_at(sq("e5")) == Piece(0, 1)
    with pytest.raises(ReplayError, match="dice say"):
        QuantumBoard.replay(fen, records, Always(0.99), check_dice=True)
