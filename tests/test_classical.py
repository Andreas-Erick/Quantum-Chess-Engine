"""Tests for the classical bitboard engine (Phase 1)."""

import pytest

from engine.bitboard import (
    BETWEEN,
    BISHOP,
    BLACK,
    KING,
    KNIGHT,
    PAWN,
    QUEEN,
    ROOK,
    WHITE,
    bishop_attacks,
    bit,
    parse_square,
    popcount,
    rook_attacks,
    square_name,
)
from engine.classical import STARTING_FEN, ClassicalBoard, Move, Outcome, Piece, perft


def sq(name: str) -> int:
    return parse_square(name)


def targets_from(board: ClassicalBoard, source: str) -> set[str]:
    return {square_name(m.target) for m in board.legal_moves() if m.source == sq(source)}


# --- Perft: reference node counts from the Chess Programming Wiki ----------------

PERFT_CASES = [
    (STARTING_FEN, [20, 400, 8902, 197281]),
    # "Kiwipete": castling, en passant, promotions and pins all at once.
    ("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", [48, 2039, 97862]),
    ("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", [14, 191, 2812, 43238]),
    ("r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1", [6, 264, 9467]),
    ("rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8", [44, 1486, 62379]),
]


@pytest.mark.parametrize("fen,counts", PERFT_CASES)
def test_perft(fen, counts):
    board = ClassicalBoard(fen)
    for depth, expected in enumerate(counts, start=1):
        assert perft(board, depth) == expected, f"depth {depth}"
    assert board.fen() == fen, "make/unmake must restore the position exactly"


# --- Bitboard primitives ----------------------------------------------------------


def test_square_naming_roundtrip():
    for i in range(64):
        assert parse_square(square_name(i)) == i
    assert sq("a1") == 0 and sq("h1") == 7 and sq("a8") == 56 and sq("h8") == 63


@pytest.mark.parametrize("bad", ["", "i1", "a9", "a10", "A1"])
def test_parse_square_rejects_garbage(bad):
    with pytest.raises(ValueError):
        parse_square(bad)


def test_slider_attacks_stop_at_first_blocker():
    occupied = bit(sq("d6")) | bit(sq("b4"))
    attacks = rook_attacks(sq("d4"), occupied)
    assert attacks & bit(sq("d6")) and not attacks & bit(sq("d7"))
    assert attacks & bit(sq("b4")) and not attacks & bit(sq("a4"))
    assert popcount(rook_attacks(sq("d4"), 0)) == 14
    assert popcount(bishop_attacks(sq("d4"), 0)) == 13


def test_between():
    assert BETWEEN[sq("a1")][sq("a4")] == bit(sq("a2")) | bit(sq("a3"))
    assert BETWEEN[sq("c1")][sq("f4")] == bit(sq("d2")) | bit(sq("e3"))
    assert BETWEEN[sq("a1")][sq("b3")] == 0  # not on a common line


# --- Piece movement ---------------------------------------------------------------


def test_knight_moves_from_center_and_corner():
    board = ClassicalBoard("4k3/8/8/8/3N4/8/8/N3K3 w - - 0 1")
    assert targets_from(board, "d4") == {"b3", "b5", "c2", "c6", "e2", "e6", "f3", "f5"}
    assert targets_from(board, "a1") == {"b3", "c2"}


def test_bishop_is_blocked_by_own_piece_and_captures_enemy():
    board = ClassicalBoard("4k3/8/5p2/8/3B4/8/1P6/4K3 w - - 0 1")
    assert targets_from(board, "d4") == {"c3", "e3", "f2", "g1", "c5", "b6", "a7", "e5", "f6"}


def test_rook_moves():
    board = ClassicalBoard("4k3/3p4/8/8/3R4/8/8/4K3 w - - 0 1")
    expected = {"d5", "d6", "d7", "d3", "d2", "d1", "a4", "b4", "c4", "e4", "f4", "g4", "h4"}
    assert targets_from(board, "d4") == expected


def test_queen_combines_rook_and_bishop():
    board = ClassicalBoard("7k/8/8/8/3Q4/8/K7/8 w - - 0 1")
    assert len(targets_from(board, "d4")) == 27


def test_king_cannot_step_into_attack():
    board = ClassicalBoard("4k3/8/8/8/8/8/r7/4K3 w - - 0 1")
    # The rook on a2 controls the whole second rank.
    assert targets_from(board, "e1") == {"d1", "f1"}


def test_pawn_single_double_and_capture():
    board = ClassicalBoard("4k3/8/8/8/8/3p4/4P3/4K3 w - - 0 1")
    assert targets_from(board, "e2") == {"e3", "e4", "d3"}


def test_pawn_blocked():
    board = ClassicalBoard("4k3/8/8/8/8/4n3/4P3/4K3 w - - 0 1")
    assert targets_from(board, "e2") == set()


def test_black_pawns_move_down():
    board = ClassicalBoard("4k3/3p4/8/8/8/8/8/4K3 b - - 0 1")
    assert targets_from(board, "d7") == {"d6", "d5"}


def test_en_passant():
    board = ClassicalBoard()
    for uci in ["e2e4", "a7a6", "e4e5", "d7d5"]:
        board.play(uci)
    assert board.ep_square == sq("d6")
    board.play("e5d6")
    assert board.piece_at(sq("d5")) is None
    assert board.piece_at(sq("d6")) == Piece(WHITE, PAWN)


def test_en_passant_expires_after_one_move():
    board = ClassicalBoard()
    for uci in ["e2e4", "a7a6", "e4e5", "d7d5", "h2h3", "h7h6"]:
        board.play(uci)
    assert Move.from_uci("e5d6") not in board.legal_moves()


def test_promotion_generates_all_four_pieces():
    board = ClassicalBoard("4k3/P7/8/8/8/8/8/4K3 w - - 0 1")
    promos = {m.promotion for m in board.legal_moves() if m.source == sq("a7")}
    assert promos == {QUEEN, ROOK, BISHOP, KNIGHT}
    board.play("a7a8n")
    assert board.piece_at(sq("a8")) == Piece(WHITE, KNIGHT)


def test_castling_both_sides():
    board = ClassicalBoard("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    assert {"g1", "c1"} <= targets_from(board, "e1")
    board.play("e1g1")
    assert board.piece_at(sq("f1")) == Piece(WHITE, ROOK)
    assert board.piece_at(sq("h1")) is None
    board.play("e8c8")
    assert board.piece_at(sq("d8")) == Piece(BLACK, ROOK)
    assert board.castling == 0


def test_cannot_castle_through_check():
    board = ClassicalBoard("4k3/8/8/8/8/8/5r2/R3K2R w KQ - 0 1")
    # The rook on f2 attacks f1, a square the king must pass through.
    assert "g1" not in targets_from(board, "e1")
    assert "c1" in targets_from(board, "e1")


def test_cannot_castle_out_of_check():
    board = ClassicalBoard("4r1k1/8/8/8/8/8/8/R3K2R w KQ - 0 1")
    assert not {"g1", "c1"} & targets_from(board, "e1")


def test_moving_rook_loses_castling_right():
    board = ClassicalBoard("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    board.play("h1h2")
    board.play("a8a7")
    assert board.fen().split()[2] == "Qk"


def test_pinned_piece_cannot_move():
    board = ClassicalBoard("4k3/4r3/8/8/8/8/4N3/4K3 w - - 0 1")
    assert targets_from(board, "e2") == set()


def test_must_resolve_check():
    board = ClassicalBoard("4k3/8/8/8/8/8/8/r3K2R w K - 0 1")
    for move in board.legal_moves():
        board.push(move)
        assert not board.is_attacked(board.king_square(WHITE), BLACK)
        board.pop()


# --- Move API ---------------------------------------------------------------------


def test_uci_roundtrip():
    for text in ["e2e4", "a7a8q", "h7h8n"]:
        assert Move.from_uci(text).uci() == text


def test_play_rejects_illegal_move():
    board = ClassicalBoard()
    with pytest.raises(ValueError):
        board.play("e2e5")
    assert board.fen() == STARTING_FEN


def test_push_pop_restores_state():
    board = ClassicalBoard()
    board.push(Move.from_uci("e2e4"))
    board.pop()
    assert board.fen() == STARTING_FEN


def test_fen_roundtrip():
    for fen, _ in PERFT_CASES:
        assert ClassicalBoard(fen).fen() == fen


@pytest.mark.parametrize(
    "fen", ["", "8/8/8 w - - 0 1", "9/8/8/8/8/8/8/8 w - - 0 1", "8/8/8/8/8/8/8/8 x - - 0 1"]
)
def test_invalid_fen(fen):
    with pytest.raises(ValueError):
        ClassicalBoard(fen)


# --- Game outcomes ----------------------------------------------------------------


def test_fools_mate():
    board = ClassicalBoard()
    for uci in ["f2f3", "e7e5", "g2g4", "d8h4"]:
        board.play(uci)
    assert board.is_checkmate()
    assert board.outcome() == Outcome.CHECKMATE
    assert board.winner() == BLACK


def test_stalemate():
    board = ClassicalBoard("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
    assert board.outcome() == Outcome.STALEMATE
    assert board.winner() is None


@pytest.mark.parametrize(
    "fen,expected",
    [
        ("8/8/4k3/8/8/4K3/8/8 w - - 0 1", True),  # K vs K
        ("8/8/4k3/8/8/4KN2/8/8 w - - 0 1", True),  # K+N vs K
        ("8/8/4k3/8/8/4KB2/8/8 w - - 0 1", True),  # K+B vs K
        ("8/8/4kb2/8/8/4KB2/8/8 w - - 0 1", False),  # bishops on opposite colours
        ("8/8/4k3/8/8/4KR2/8/8 w - - 0 1", False),  # rook mates
    ],
)
def test_insufficient_material(fen, expected):
    assert ClassicalBoard(fen).is_insufficient_material() is expected


def test_threefold_repetition():
    board = ClassicalBoard()
    for _ in range(2):
        for uci in ["g1f3", "g8f6", "f3g1", "f6g8"]:
            board.play(uci)
    assert board.outcome() == Outcome.THREEFOLD_REPETITION


def test_fifty_move_rule():
    board = ClassicalBoard("8/8/4k3/8/8/4KR2/8/8 w - - 100 80")
    assert board.outcome() == Outcome.FIFTY_MOVES


def test_king_piece_identity():
    board = ClassicalBoard()
    assert board.piece_at(sq("e1")) == Piece(WHITE, KING)
    assert board.piece_at(sq("e8")).symbol == "k"
