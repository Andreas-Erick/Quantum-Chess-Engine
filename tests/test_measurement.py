"""Phase 2: measurement, collapse and captures involving superposed pieces."""

import numpy as np
import pytest

from engine.bitboard import BISHOP, BLACK, KING, KNIGHT, QUEEN, WHITE, parse_square
from engine.board import IllegalMoveError, QuantumBoard
from engine.classical import Piece


class FixedRng:
    """Forces measurement outcomes: 0.0 finds the piece whenever p > 0, ~1.0 never does."""

    def __init__(self, value: float) -> None:
        self.value = value

    def random(self) -> float:
        return self.value


FOUND = FixedRng(0.0)
MISSING = FixedRng(1 - 1e-12)

# White knight b1 (to split onto a3/c3), black bishop e5 eyeing c3, black pawn e4.
CAPTURE_FEN = "4k3/8/8/4b3/4p3/8/8/1N2K3 w - - 0 1"


def sq(name: str) -> int:
    return parse_square(name)


def split_knight(rng) -> QuantumBoard:
    board = QuantumBoard(CAPTURE_FEN, rng=rng)
    board.do_move("b1^a3c3")
    return board


# --- Capturing a superposed piece ---------------------------------------------------


def test_capture_superposed_target_found():
    board = split_knight(FOUND)
    result = board.do_move("e5c3")
    assert result.executed
    assert result.captured == Piece(WHITE, KNIGHT)
    [m] = result.measurements
    assert m.square == sq("c3") and m.occupied and m.probability == pytest.approx(0.5)
    # Chain reaction: the knight was on c3, so the a3 half vanishes too.
    assert m.collapsed == {sq("c3"): True, sq("a3"): False}
    assert board.piece_at(sq("c3")) == Piece(BLACK, BISHOP)
    assert board.piece_at(sq("a3")) is None
    assert len(board.register) == 0


def test_capture_superposed_target_missing_becomes_plain_move():
    board = split_knight(MISSING)
    result = board.do_move("e5c3")
    assert result.executed and result.captured is None
    assert board.piece_at(sq("c3")) == Piece(BLACK, BISHOP)
    assert board.probability(sq("a3")) == 1.0  # the knight is certainly on a3 now


# --- Capturing with a superposed piece ----------------------------------------------


def test_superposed_attacker_present_captures():
    board = split_knight(FOUND)
    board.do_move("e8d8")
    result = board.do_move("c3e4")
    assert result.executed and result.captured == Piece(BLACK, 0)
    assert board.piece_at(sq("e4")) == Piece(WHITE, KNIGHT)
    assert board.piece_at(sq("a3")) is None


def test_superposed_attacker_absent_move_fails_but_turn_passes():
    board = split_knight(MISSING)
    board.do_move("e8d8")
    result = board.do_move("c3e4")
    assert not result.executed and result.captured is None
    assert board.turn == BLACK
    assert board.piece_at(sq("e4")) == Piece(BLACK, 0)
    assert board.piece_at(sq("a3")) == Piece(WHITE, KNIGHT)
    assert board.is_classical(sq("a3"))


# --- Other measurement triggers ------------------------------------------------------


def test_moving_onto_own_superposed_piece_measures_it():
    board = QuantumBoard("4k3/8/8/8/8/8/8/1N2K1N1 w - - 0 1", rng=FOUND)
    board.do_move("b1^a3c3")
    board.do_move("e8d8")
    result = board.do_move("e1d2")  # warm-up: classical king move
    assert result.executed
    board.do_move("d8e8")
    result = board.do_move("d2c3")  # c3 might hold our own knight
    assert not result.executed  # it did: the king is blocked
    assert board.piece_at(sq("c3")) == Piece(WHITE, KNIGHT)
    assert board.piece_at(sq("d2")) == Piece(WHITE, KING)


def test_pawn_push_into_superposed_square():
    fen = "4k3/8/8/8/8/8/2P5/1N2K3 w - - 0 1"
    board = QuantumBoard(fen, rng=FOUND)
    board.do_move("b1^a3c3")
    board.do_move("e8d8")
    result = board.do_move("c2c3")
    assert not result.executed  # knight was there; pawns cannot capture forwards

    board = QuantumBoard(fen, rng=MISSING)
    board.do_move("b1^a3c3")
    board.do_move("e8d8")
    assert board.do_move("c2c3").executed


def test_measurement_statistics_follow_born_rule():
    found = 0
    trials = 300
    for seed in range(trials):
        board = split_knight(np.random.default_rng(seed))
        if board.do_move("e5c3").captured is not None:
            found += 1
    # 50% expected; 4 standard deviations is about +/- 35.
    assert abs(found - trials / 2) < 35


def test_quarter_probability_statistics():
    found = 0
    trials = 400
    for seed in range(trials):
        board = QuantumBoard("4k3/8/8/8/7r/8/8/1N2K3 w - - 0 1", rng=np.random.default_rng(seed))
        board.do_move("b1^a3c3")
        board.do_move("e8d8")
        board.do_move("c3^d5e4")  # e4 now holds the knight with probability 1/4
        result = board.do_move("h4e4")
        assert result.measurements[0].probability == pytest.approx(0.25)
        found += result.captured is not None
    # 100 expected; 4 standard deviations is about +/- 35.
    assert abs(found - trials / 4) < 35


# --- Game end -----------------------------------------------------------------------


def test_capturing_the_king_wins():
    board = QuantumBoard("4k3/8/8/8/8/8/8/4KQ2 w - - 0 1")
    board.do_move("f1f8")
    board.do_move("e8e7")
    result = board.do_move("f8e7")  # no check rule: the king walked into it
    assert result.winner == WHITE and board.winner == WHITE
    with pytest.raises(IllegalMoveError):
        board.do_move("e1e2")
    assert board.legal_moves() == []


def test_superposed_king_survives_a_miss():
    board = QuantumBoard("4k3/8/8/8/8/8/8/3QK3 w - - 0 1", rng=MISSING)
    board.do_move("d1d7")
    board.do_move("e8^f8f7")
    result = board.do_move("d7f7")
    assert result.executed and result.captured is None and board.winner is None
    assert board.piece_at(sq("f8")) == Piece(BLACK, KING)
    assert board.piece_at(sq("f7")) == Piece(WHITE, QUEEN)


def test_castling():
    board = QuantumBoard("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    board.do_move("e1g1")
    assert board.piece_at(sq("f1")) == Piece(WHITE, 3)
    board.do_move("e8c8")
    assert board.piece_at(sq("d8")) == Piece(BLACK, 3)
    assert board.castling == 0
