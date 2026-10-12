"""Phase 2: split / merge / jump unitaries and the sparse register."""

import cirq
import numpy as np
import pytest

from engine.bitboard import KNIGHT, WHITE, parse_square
from engine.board import IllegalMoveError, QuantumBoard
from engine.classical import Piece
from engine.moves import MoveType, QuantumMove, merge_ops, split_ops
from engine.register import QuantumRegister

# White knight on b1, kings far away, black to make waiting moves with the king.
KNIGHT_FEN = "4k3/8/8/8/8/8/8/1N2K3 w - - 0 1"


def sq(name: str) -> int:
    return parse_square(name)


def p(board: QuantumBoard, name: str) -> float:
    return board.probability(sq(name))


# --- Notation --------------------------------------------------------------------


@pytest.mark.parametrize("text", ["e2e4", "e7e8q", "b1^a3c3", "a3c3^b1"])
def test_notation_roundtrip(text):
    assert QuantumMove.parse(text).notation() == text


def test_notation_types():
    assert QuantumMove.parse("b1^a3c3").move_type is MoveType.SPLIT
    assert QuantumMove.parse("a3c3^b1").move_type is MoveType.MERGE
    assert QuantumMove.parse("b1c3").move_type is MoveType.JUMP


@pytest.mark.parametrize("text", ["", "b1^a3", "a3^b1c3d4", "e2e4k", "z9a1"])
def test_bad_notation(text):
    with pytest.raises(ValueError):
        QuantumMove.parse(text)


# --- Gates in isolation ----------------------------------------------------------


def test_split_unitary_gives_equal_amplitudes():
    s, a, b = cirq.LineQubit.range(3)
    circuit = cirq.Circuit([cirq.X(s)] + split_ops(s, a, b))
    state = cirq.final_state_vector(circuit, dtype=np.complex128)
    probs = np.abs(state) ** 2
    # Big-endian basis: index 0b010 = piece on a, 0b001 = piece on b.
    assert probs[0b010] == pytest.approx(0.5)
    assert probs[0b001] == pytest.approx(0.5)


def test_merge_undoes_split():
    s, a, b = cirq.LineQubit.range(3)
    circuit = cirq.Circuit([cirq.X(s)] + split_ops(s, a, b) + merge_ops(a, b, s))
    state = cirq.final_state_vector(circuit, dtype=np.complex128)
    assert abs(state[0b100]) == pytest.approx(1.0)


def test_register_add_and_release():
    reg = QuantumRegister()
    reg.add(0, occupied=True)
    reg.add(1, occupied=False)
    assert reg.probability(0) == 1.0 and reg.probability(1) == 0.0
    assert reg.release_definite() == {0: True, 1: False}
    assert len(reg) == 0


# --- Split -----------------------------------------------------------------------


def test_split_creates_fifty_fifty():
    board = QuantumBoard(KNIGHT_FEN)
    board.do_move("b1^a3c3")
    assert p(board, "a3") == pytest.approx(0.5)
    assert p(board, "c3") == pytest.approx(0.5)
    assert p(board, "b1") == 0.0
    assert board.piece_at(sq("a3")) == Piece(WHITE, KNIGHT)
    assert board.piece_at(sq("b1")) is None


def test_split_keeps_register_minimal():
    board = QuantumBoard(KNIGHT_FEN)
    board.do_move("b1^a3c3")
    # The source became certainly empty and was handed back to the classical board.
    assert set(board.register.squares) == {sq("a3"), sq("c3")}


def test_probabilities_conserve_piece_count():
    board = QuantumBoard()
    for move in ["g1^f3h3", "b8^a6c6", "b1^a3c3", "g8^f6h6"]:
        board.do_move(move)
    probs = board.probabilities()
    assert len(probs) == 64
    assert sum(probs) == pytest.approx(32.0)


def test_split_of_superposed_piece_quarters_it():
    board = QuantumBoard(KNIGHT_FEN)
    board.do_move("b1^a3c3")
    board.do_move("e8d8")
    board.do_move("c3^d5e4")
    assert p(board, "a3") == pytest.approx(0.5)
    assert p(board, "d5") == pytest.approx(0.25)
    assert p(board, "e4") == pytest.approx(0.25)


def test_quarter_piece_cannot_split_again():
    board = QuantumBoard(KNIGHT_FEN)
    for move in ("b1^a3c3", "e8d8", "c3^d5e4", "d8e8"):
        board.do_move(move)
    assert not board.can_split(sq("d5"))
    assert board.can_split(sq("a3"))
    with pytest.raises(IllegalMoveError, match="too uncertain"):
        board.do_move("d5^c7f6")
    legal = {m.notation() for m in board.legal_moves()}
    assert not any(m.startswith(("d5^", "e4^")) for m in legal)
    assert any(m.startswith("a3^") for m in legal)
    assert "d5e3" in legal  # a quarter piece can still move


def test_split_cap_follows_constant(monkeypatch):
    monkeypatch.setattr("engine.board.MIN_SPLIT_FRAGMENT", 0.5)
    board = QuantumBoard(KNIGHT_FEN)
    board.do_move("b1^a3c3")
    board.do_move("e8d8")
    splits = [m for m in board.legal_moves() if m.move_type is MoveType.SPLIT]
    assert splits and all(m.source == sq("e1") for m in splits)  # only the whole king


def test_nested_split_merges_back_level_by_level():
    board = QuantumBoard(KNIGHT_FEN)
    for move in ("b1^a3c3", "e8d8", "c3^d5e4", "d8e8", "d5e4^c3", "e8d8", "a3c3^b1"):
        board.do_move(move)
    assert p(board, "b1") == pytest.approx(1.0)
    assert board.is_classical(sq("b1"))
    assert len(board.register) == 0


@pytest.mark.parametrize(
    "fen,move",
    [
        ("4k3/8/8/8/8/8/4P3/4K3 w - - 0 1", "e2^e3e4"),  # pawns cannot split
        (KNIGHT_FEN, "b1^a3a3"),  # targets must differ
        (KNIGHT_FEN, "b1^a3b3"),  # b3 not a knight move
        ("4k3/8/8/8/8/2P5/8/1N2K3 w - - 0 1", "b1^a3c3"),  # c3 occupied
        (KNIGHT_FEN, "e8^d8f8"),  # not your piece
    ],
)
def test_illegal_splits(fen, move):
    board = QuantumBoard(fen)
    with pytest.raises(IllegalMoveError):
        board.do_move(move)
    assert board.turn == WHITE  # an illegal move does not consume the turn


# --- Merge -----------------------------------------------------------------------


def test_merge_back_to_origin_restores_classical_piece():
    board = QuantumBoard(KNIGHT_FEN)
    board.do_move("b1^a3c3")
    board.do_move("e8d8")
    board.do_move("a3c3^b1")
    assert p(board, "b1") == 1.0
    assert board.is_classical(sq("b1"))
    assert len(board.register) == 0


def test_merge_onto_new_square():
    board = QuantumBoard(KNIGHT_FEN)
    board.do_move("b1^a3c3")
    board.do_move("e8d8")
    board.do_move("a3c3^b5")
    assert p(board, "b5") == 1.0
    assert p(board, "a3") == p(board, "c3") == 0.0


def test_merge_requires_superposed_sources():
    board = QuantumBoard("4k3/8/8/8/8/8/8/1N2KN2 w - - 0 1")
    with pytest.raises(IllegalMoveError):
        board.do_move("b1f1^d2")


def test_merge_with_mismatched_phase_only_partly_recombines():
    # Split, then move one half with a jump (iSWAP adds a phase of i to that half only).
    board = QuantumBoard("4k3/8/8/8/8/8/8/R3K3 w - - 0 1")
    board.do_move("a1^a4d1")
    board.do_move("e8d8")
    board.do_move("a4b4")  # the a4 half moves on, picking up a relative phase
    board.do_move("d8e8")
    board.do_move("b4d1^b1")
    # Interference is incomplete: the rook is not certainly on a1.
    assert 0.0 < p(board, "b1") < 1.0
    assert sum(board.probabilities()) == pytest.approx(3.0)


# --- Jump ------------------------------------------------------------------------


def test_superposed_piece_jumps_without_measurement():
    board = QuantumBoard(KNIGHT_FEN)
    board.do_move("b1^a3c3")
    board.do_move("e8d8")
    result = board.do_move("a3b5")
    assert result.executed and result.measurements == []
    assert p(board, "b5") == pytest.approx(0.5)
    assert p(board, "a3") == 0.0


def test_classical_moves_stay_out_of_register():
    board = QuantumBoard()
    for move in ["e2e4", "e7e5", "g1f3", "b8c6"]:
        assert board.do_move(move).executed
    assert len(board.register) == 0


def test_split_cannot_pass_through_superposed_piece():
    # Jumps may slide through superposed squares (see test_entanglement.py); splits may not.
    board = QuantumBoard("4k3/8/8/8/8/8/8/RN2K3 w - - 0 1")
    board.do_move("b1^a3c3")
    board.do_move("e8d8")
    with pytest.raises(IllegalMoveError):
        board.do_move("a1^a2a5")


def test_legal_moves_include_quantum_moves():
    board = QuantumBoard()
    moves = {m.notation() for m in board.legal_moves()}
    assert {"e2e4", "g1^f3h3", "b1^a3c3"} <= moves
    assert not any(m.startswith("e2^") for m in moves)  # no pawn splits
    for move in board.legal_moves():
        board.validate(move)


def test_legal_moves_include_merges():
    board = QuantumBoard(KNIGHT_FEN)
    board.do_move("b1^a3c3")
    board.do_move("e8d8")
    moves = {m.notation() for m in board.legal_moves()}
    assert {"a3c3^b1", "a3c3^b5"} <= moves
