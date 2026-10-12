"""Phase 3: slides through superposed squares, entanglement, and collapse chain reactions."""

import random

import numpy as np
import pytest

from engine.bitboard import BLACK, KNIGHT, PAWN, QUEEN, ROOK, WHITE, parse_square
from engine.board import QuantumBoard
from engine.classical import Piece
from engine.measurement import PathMeasurement


class FixedRng:
    """0.0 makes every possible event happen; ~1.0 makes every uncertain event fail."""

    def __init__(self, value: float) -> None:
        self.value = value

    def random(self) -> float:
        return self.value


YES = FixedRng(0.0)
NO = FixedRng(1 - 1e-12)


def sq(name: str) -> int:
    return parse_square(name)


def p(board: QuantumBoard, name: str) -> float:
    return board.probability(sq(name))


def joint(board: QuantumBoard, **occupied: bool) -> float:
    return board.joint_probability({sq(name): value for name, value in occupied.items()})


# Rook a1 and knight b1: the knight splits onto a3/c3, half-blocking the a-file.
ROOK_KNIGHT_FEN = "4k3/8/8/8/8/8/8/RN2K3 w - - 0 1"


def half_blocked_file(rng=None) -> QuantumBoard:
    board = QuantumBoard(ROOK_KNIGHT_FEN, rng=rng)
    board.do_move("b1^a3c3")
    board.do_move("e8d8")
    return board


# --- Slides --------------------------------------------------------------------------


def test_slide_through_superposed_piece_entangles():
    board = half_blocked_file()
    result = board.do_move("a1a5")
    assert result.executed and result.measurements == []
    assert p(board, "a5") == pytest.approx(0.5)
    assert p(board, "a1") == pytest.approx(0.5)
    # The rook got through exactly when the knight was not on a3.
    assert joint(board, a5=True, a3=True) == pytest.approx(0.0)
    assert joint(board, a5=True, c3=True) == pytest.approx(0.5)
    assert joint(board, a1=True, a3=True) == pytest.approx(0.5)


def test_slide_is_legal_but_split_through_is_not():
    board = half_blocked_file()
    moves = {m.notation() for m in board.legal_moves()}
    assert "a1a5" in moves
    assert "a1^a2a5" not in moves


def test_slide_through_two_independent_blockers():
    board = QuantumBoard("1n2k3/8/8/8/8/8/8/RN2K3 w - - 0 1")
    board.do_move("b1^a3c3")
    board.do_move("b8^a6c6")
    board.do_move("a1a7")
    assert p(board, "a7") == pytest.approx(0.25)
    assert joint(board, a7=True, c3=True, c6=True) == pytest.approx(0.25)


def test_slide_conserves_pieces():
    board = half_blocked_file()
    board.do_move("a1a5")
    assert sum(board.probabilities()) == pytest.approx(4.0)


def test_pawn_double_push_slides_over_superposed_square():
    board = QuantumBoard("4k3/8/8/8/8/8/4P3/4KN2 w - - 0 1")
    board.do_move("f1^e3g3")
    board.do_move("e8d8")
    board.do_move("e2e4")
    assert p(board, "e4") == pytest.approx(0.5)
    assert p(board, "e2") == pytest.approx(0.5)
    assert board.piece_at(sq("e2")) == board.piece_at(sq("e4")) == Piece(WHITE, PAWN)
    assert joint(board, e4=True, g3=True) == pytest.approx(0.5)


def test_superposed_piece_slides_through_superposed_square():
    board = QuantumBoard("4k3/8/8/8/8/8/8/R1N1K3 w - - 0 1")
    board.do_move("c1^b3e2")  # knight half-blocks the third rank on b3
    board.do_move("e8d8")
    board.do_move("a1^a2a3")  # rook half on a3
    board.do_move("d8e8")
    board.do_move("a3e3")  # rook there (1/2) and path clear (1/2)
    assert p(board, "e3") == pytest.approx(0.25)
    assert p(board, "a3") == pytest.approx(0.25)
    assert sum(board.probabilities()) == pytest.approx(4.0)


# --- Captures along a superposed path ---------------------------------------------------

CAPTURE_FEN = "4k3/8/8/r7/8/8/8/RN2K3 w - - 0 1"


def test_capture_along_clear_path():
    board = QuantumBoard(CAPTURE_FEN, rng=YES)
    board.do_move("b1^a3c3")
    board.do_move("e8d8")
    result = board.do_move("a1a5")
    [m] = result.measurements
    assert isinstance(m, PathMeasurement)
    assert m.path == (sq("a3"),) and m.clear and m.probability == pytest.approx(0.5)
    assert result.executed and result.captured == Piece(BLACK, ROOK)
    assert board.piece_at(sq("a5")) == Piece(WHITE, ROOK)
    assert p(board, "c3") == 1.0  # a clear path means the knight was on c3


def test_capture_along_blocked_path_fails():
    board = QuantumBoard(CAPTURE_FEN, rng=NO)
    board.do_move("b1^a3c3")
    board.do_move("e8d8")
    result = board.do_move("a1a5")
    assert not result.executed and result.captured is None
    assert board.turn == BLACK
    assert board.piece_at(sq("a1")) == Piece(WHITE, ROOK)
    assert board.piece_at(sq("a5")) == Piece(BLACK, ROOK)
    assert p(board, "a3") == 1.0


def test_path_measurement_answers_only_whether_path_is_clear():
    # Two independent possible blockers on the a-file; the capture finds the path blocked.
    board = QuantumBoard("rn2k3/8/8/8/8/8/8/RN2K3 w - - 0 1", rng=NO)
    board.do_move("b1^a3c3")
    board.do_move("b8^a6c6")
    result = board.do_move("a1a8")
    [m] = result.measurements
    assert m.probability == pytest.approx(0.25) and not m.clear
    assert not result.executed
    # "Blocked" leaves three equally likely worlds: (a3, a6), (a3, c6), (c3, a6).
    # Neither blocker is revealed, but the two knights are now entangled.
    assert p(board, "a3") == pytest.approx(2 / 3)
    assert p(board, "a6") == pytest.approx(2 / 3)
    assert joint(board, c3=True, c6=True) == pytest.approx(0.0)
    assert len(board.register.groups) == 1


# --- Entanglement chains ------------------------------------------------------------------

# Knight b1, rook a3, queen e1, black rook c8. Kings in the corners.
CHAIN_FEN = "2r4k/8/8/8/8/R7/8/1N2Q2K w - - 0 1"


def build_chain(rng=None) -> QuantumBoard:
    """Knight on c3 or d2. Rook a3->e3 needs c3 empty. Queen e1->e5 needs e3 empty.

    So: knight on c3  <=>  rook stuck on a3  <=>  queen reached e5.
    """
    board = QuantumBoard(CHAIN_FEN, rng=rng)
    for move in ["b1^c3d2", "h8g8", "a3e3", "g8h8", "e1e5"]:
        assert board.do_move(move).executed
    return board


def test_chain_correlations():
    board = build_chain()
    for name in ["c3", "d2", "a3", "e3", "e1", "e5"]:
        assert p(board, name) == pytest.approx(0.5)
    assert joint(board, c3=True, a3=True, e5=True) == pytest.approx(0.5)
    assert joint(board, d2=True, e3=True, e1=True) == pytest.approx(0.5)
    assert joint(board, c3=True, e1=True) == pytest.approx(0.0)
    assert board.register.groups == [tuple(board.register.squares)]  # one entangled group


def test_capturing_the_root_collapses_the_whole_chain():
    board = build_chain(YES)
    result = board.do_move("c8c3")
    [m] = result.measurements
    assert m.occupied and result.captured == Piece(WHITE, KNIGHT)
    expected = {"c3": True, "d2": False, "a3": True, "e3": False, "e5": True, "e1": False}
    assert m.collapsed == {sq(name): value for name, value in expected.items()}
    assert len(board.register) == 0
    assert board.piece_at(sq("c3")) == Piece(BLACK, ROOK)
    assert board.piece_at(sq("a3")) == Piece(WHITE, ROOK)
    assert board.piece_at(sq("e5")) == Piece(WHITE, QUEEN)
    assert board.piece_at(sq("d2")) is None and board.piece_at(sq("e1")) is None


def test_missing_the_root_collapses_the_chain_the_other_way():
    board = build_chain(NO)
    result = board.do_move("c8c3")
    assert result.executed and result.captured is None
    assert len(board.register) == 0
    assert board.piece_at(sq("d2")) == Piece(WHITE, KNIGHT)
    assert board.piece_at(sq("e3")) == Piece(WHITE, ROOK)
    assert board.piece_at(sq("e1")) == Piece(WHITE, QUEEN)


def test_measuring_the_end_of_the_chain_collapses_the_root():
    # Black bishop on b8 can capture on e5, the far end of the chain.
    board = QuantumBoard("1b5k/8/8/8/8/R7/8/1N2Q2K w - - 0 1", rng=YES)
    for move in ["b1^c3d2", "h8g8", "a3e3", "g8h8", "e1e5"]:
        board.do_move(move)
    result = board.do_move("b8e5")
    assert result.captured == Piece(WHITE, QUEEN)
    assert board.piece_at(sq("c3")) == Piece(WHITE, KNIGHT)
    assert board.piece_at(sq("a3")) == Piece(WHITE, ROOK)
    assert len(board.register) == 0


def test_chain_outcomes_are_always_consistent():
    outcomes = {True: 0, False: 0}
    for seed in range(100):
        board = build_chain(np.random.default_rng(seed))
        found = board.do_move("c8c3").captured is not None
        outcomes[found] += 1
        # Whatever happened, the board is classical and consistent with the chain.
        assert len(board.register) == 0
        assert (board.piece_at(sq("e5")) is not None) == found
        assert (board.piece_at(sq("a3")) is not None) == found
    assert outcomes[True] > 25 and outcomes[False] > 25


# --- Register groups -----------------------------------------------------------------------


def test_independent_pieces_stay_in_separate_groups():
    board = QuantumBoard("1n2k3/8/8/8/8/8/8/RN2K3 w - - 0 1")
    board.do_move("b1^a3c3")
    board.do_move("b8^a6c6")
    assert sorted(map(sorted, board.register.groups)) == [
        sorted([sq("a3"), sq("c3")]),
        sorted([sq("a6"), sq("c6")]),
    ]
    assert board.register.largest_group == 2


def test_slide_joins_groups():
    board = QuantumBoard("1n2k3/8/8/8/8/8/8/RN2K3 w - - 0 1")
    board.do_move("b1^a3c3")
    board.do_move("b8^a6c6")
    board.do_move("a1a7")
    assert len(board.register.groups) == 1
    assert board.register.largest_group == 6


# --- Random play invariants ----------------------------------------------------------------


@pytest.mark.parametrize("seed", range(8))
def test_random_games_preserve_invariants(seed):
    chooser = random.Random(seed)
    board = QuantumBoard(rng=np.random.default_rng(seed))
    for _ in range(80):
        moves = board.legal_moves()
        if not moves or board.register.largest_group > 12:
            break
        before = sum(board.probabilities())
        result = board.do_move(chooser.choice(moves))
        after = sum(board.probabilities())
        assert after == pytest.approx(before - (result.captured is not None))
        for s in board.register.squares:
            assert 0 < board.probability(s) < 1
            assert board.piece_at(s) is not None
