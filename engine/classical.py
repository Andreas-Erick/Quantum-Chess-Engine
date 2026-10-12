"""Classical chess engine built on bitboards.

This is the rules layer the quantum engine sits on top of: it validates the
*shape* of a move (how each piece type moves, castling, en passant, promotion)
and tracks game state. It is a complete, perft-verified implementation of
standard chess.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from engine.bitboard import (
    BETWEEN,
    BISHOP,
    BLACK,
    FILE_NAMES,
    KING,
    KING_ATTACKS,
    KNIGHT,
    KNIGHT_ATTACKS,
    PAWN,
    PAWN_ATTACKS,
    PIECE_SYMBOLS,
    QUEEN,
    ROOK,
    WHITE,
    bishop_attacks,
    bit,
    iter_squares,
    lsb,
    parse_square,
    popcount,
    rank_of,
    rook_attacks,
    square,
    square_name,
)

STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

# Castling-rights bitmask.
WHITE_KINGSIDE, WHITE_QUEENSIDE, BLACK_KINGSIDE, BLACK_QUEENSIDE = 1, 2, 4, 8
_CASTLING_CHARS = (
    ("K", WHITE_KINGSIDE),
    ("Q", WHITE_QUEENSIDE),
    ("k", BLACK_KINGSIDE),
    ("q", BLACK_QUEENSIDE),
)

# Rights lost when a piece moves from or to a given square (rook/king homes).
CASTLING_MASK = [0] * 64
CASTLING_MASK[square(4, 0)] = WHITE_KINGSIDE | WHITE_QUEENSIDE
CASTLING_MASK[square(7, 0)] = WHITE_KINGSIDE
CASTLING_MASK[square(0, 0)] = WHITE_QUEENSIDE
CASTLING_MASK[square(4, 7)] = BLACK_KINGSIDE | BLACK_QUEENSIDE
CASTLING_MASK[square(7, 7)] = BLACK_KINGSIDE
CASTLING_MASK[square(0, 7)] = BLACK_QUEENSIDE

PROMOTION_PIECES = (QUEEN, ROOK, BISHOP, KNIGHT)


@dataclass(frozen=True)
class Piece:
    color: int
    kind: int

    @property
    def symbol(self) -> str:
        s = PIECE_SYMBOLS[self.kind]
        return s.upper() if self.color == WHITE else s

    @classmethod
    def from_symbol(cls, symbol: str) -> "Piece":
        kind = PIECE_SYMBOLS.index(symbol.lower())
        return cls(WHITE if symbol.isupper() else BLACK, kind)


@dataclass(frozen=True)
class Move:
    source: int
    target: int
    promotion: Optional[int] = None

    def uci(self) -> str:
        promo = PIECE_SYMBOLS[self.promotion] if self.promotion is not None else ""
        return square_name(self.source) + square_name(self.target) + promo

    @classmethod
    def from_uci(cls, text: str) -> "Move":
        if len(text) not in (4, 5):
            raise ValueError(f"invalid UCI move: {text!r}")
        promo = None
        if len(text) == 5:
            if text[4] not in "nbrq":
                raise ValueError(f"invalid promotion piece in {text!r}")
            promo = PIECE_SYMBOLS.index(text[4])
        return cls(parse_square(text[:2]), parse_square(text[2:4]), promo)

    def __str__(self) -> str:
        return self.uci()


class Outcome(Enum):
    CHECKMATE = "checkmate"
    STALEMATE = "stalemate"
    FIFTY_MOVES = "fifty_moves"
    THREEFOLD_REPETITION = "threefold_repetition"
    INSUFFICIENT_MATERIAL = "insufficient_material"


class ClassicalBoard:
    """A mutable chess position with legal move generation and make/unmake."""

    def __init__(self, fen: str = STARTING_FEN) -> None:
        self.set_fen(fen)

    # --- Setup / serialisation -------------------------------------------------

    def set_fen(self, fen: str) -> None:
        fields = fen.split()
        if len(fields) < 4:
            raise ValueError(f"invalid FEN: {fen!r}")
        placement, side, castling, ep = fields[:4]
        halfmove = int(fields[4]) if len(fields) > 4 else 0
        fullmove = int(fields[5]) if len(fields) > 5 else 1

        self.pieces = [[0] * 6 for _ in range(2)]
        self.mailbox: list[Optional[Piece]] = [None] * 64
        ranks = placement.split("/")
        if len(ranks) != 8:
            raise ValueError(f"invalid FEN placement: {placement!r}")
        for i, row in enumerate(ranks):
            r, f = 7 - i, 0
            for ch in row:
                if ch.isdigit():
                    f += int(ch)
                else:
                    if f > 7:
                        raise ValueError(f"FEN rank too long: {row!r}")
                    self._put(square(f, r), Piece.from_symbol(ch))
                    f += 1
            if f != 8:
                raise ValueError(f"FEN rank has wrong length: {row!r}")

        if side not in ("w", "b"):
            raise ValueError(f"invalid side to move: {side!r}")
        self.turn = WHITE if side == "w" else BLACK
        self.castling = 0
        for ch, flag in _CASTLING_CHARS:
            if ch in castling:
                self.castling |= flag
        self.ep_square: Optional[int] = None if ep == "-" else parse_square(ep)
        self.halfmove_clock = halfmove
        self.fullmove_number = fullmove
        self._history: list[tuple] = []
        self._repetitions: list[tuple] = [self._position_key()]

    def fen(self) -> str:
        rows = []
        for r in range(7, -1, -1):
            row, empty = "", 0
            for f in range(8):
                piece = self.mailbox[square(f, r)]
                if piece is None:
                    empty += 1
                    continue
                if empty:
                    row += str(empty)
                    empty = 0
                row += piece.symbol
            rows.append(row + (str(empty) if empty else ""))
        castling = "".join(ch for ch, flag in _CASTLING_CHARS if self.castling & flag)
        ep = square_name(self.ep_square) if self.ep_square is not None else "-"
        return " ".join(
            [
                "/".join(rows),
                "w" if self.turn == WHITE else "b",
                castling or "-",
                ep,
                str(self.halfmove_clock),
                str(self.fullmove_number),
            ]
        )

    def copy(self) -> "ClassicalBoard":
        clone = ClassicalBoard.__new__(ClassicalBoard)
        clone.pieces = [list(p) for p in self.pieces]
        clone.mailbox = list(self.mailbox)
        clone.turn = self.turn
        clone.castling = self.castling
        clone.ep_square = self.ep_square
        clone.halfmove_clock = self.halfmove_clock
        clone.fullmove_number = self.fullmove_number
        clone._history = list(self._history)
        clone._repetitions = list(self._repetitions)
        return clone

    def __str__(self) -> str:
        rows = []
        for r in range(7, -1, -1):
            cells = [(p.symbol if (p := self.mailbox[square(f, r)]) else ".") for f in range(8)]
            rows.append(f"{r + 1} " + " ".join(cells))
        rows.append("  " + " ".join(FILE_NAMES))
        return "\n".join(rows)

    # --- Board queries ---------------------------------------------------------

    def piece_at(self, sq: int) -> Optional[Piece]:
        return self.mailbox[sq]

    def occupied_by(self, color: int) -> int:
        bb = 0
        for p in self.pieces[color]:
            bb |= p
        return bb

    @property
    def occupied(self) -> int:
        return self.occupied_by(WHITE) | self.occupied_by(BLACK)

    def king_square(self, color: int) -> Optional[int]:
        kings = self.pieces[color][KING]
        return lsb(kings) if kings else None

    def attackers(self, sq: int, by_color: int, occupied: Optional[int] = None) -> int:
        """Bitboard of ``by_color`` pieces attacking ``sq``."""
        if occupied is None:
            occupied = self.occupied
        p = self.pieces[by_color]
        diag = bishop_attacks(sq, occupied)
        ortho = rook_attacks(sq, occupied)
        return (
            (PAWN_ATTACKS[by_color ^ 1][sq] & p[PAWN])
            | (KNIGHT_ATTACKS[sq] & p[KNIGHT])
            | (KING_ATTACKS[sq] & p[KING])
            | (diag & (p[BISHOP] | p[QUEEN]))
            | (ortho & (p[ROOK] | p[QUEEN]))
        )

    def is_attacked(self, sq: int, by_color: int) -> bool:
        return self.attackers(sq, by_color) != 0

    def is_check(self) -> bool:
        king = self.king_square(self.turn)
        return king is not None and self.is_attacked(king, self.turn ^ 1)

    # --- Move generation -------------------------------------------------------

    def pseudo_legal_moves(self) -> list[Move]:
        """Moves that follow piece-movement rules but may leave the king in check."""
        us, them = self.turn, self.turn ^ 1
        own = self.occupied_by(us)
        enemy = self.occupied_by(them)
        occupied = own | enemy
        p = self.pieces[us]
        moves: list[Move] = []

        self._gen_pawn_moves(moves, us, enemy, occupied)

        for src in iter_squares(p[KNIGHT]):
            self._add_targets(moves, src, KNIGHT_ATTACKS[src] & ~own)
        for src in iter_squares(p[BISHOP]):
            self._add_targets(moves, src, bishop_attacks(src, occupied) & ~own)
        for src in iter_squares(p[ROOK]):
            self._add_targets(moves, src, rook_attacks(src, occupied) & ~own)
        for src in iter_squares(p[QUEEN]):
            targets = (bishop_attacks(src, occupied) | rook_attacks(src, occupied)) & ~own
            self._add_targets(moves, src, targets)
        for src in iter_squares(p[KING]):
            self._add_targets(moves, src, KING_ATTACKS[src] & ~own)

        self._gen_castling(moves, us, occupied)
        return moves

    def legal_moves(self) -> list[Move]:
        legal = []
        us = self.turn
        for move in self.pseudo_legal_moves():
            self.push(move)
            king = self.king_square(us)
            if king is None or not self.is_attacked(king, us ^ 1):
                legal.append(move)
            self.pop()
        return legal

    def is_legal(self, move: Move) -> bool:
        return move in self.legal_moves()

    @staticmethod
    def _add_targets(moves: list[Move], src: int, targets: int) -> None:
        for dst in iter_squares(targets):
            moves.append(Move(src, dst))

    def _gen_pawn_moves(self, moves: list[Move], us: int, enemy: int, occupied: int) -> None:
        forward = 8 if us == WHITE else -8
        start_rank = 1 if us == WHITE else 6
        promo_rank = 7 if us == WHITE else 0
        capturable = enemy | (bit(self.ep_square) if self.ep_square is not None else 0)

        for src in iter_squares(self.pieces[us][PAWN]):
            targets = PAWN_ATTACKS[us][src] & capturable
            one = src + forward
            if 0 <= one < 64 and not occupied & bit(one):
                targets |= bit(one)
                two = one + forward
                if rank_of(src) == start_rank and not occupied & bit(two):
                    targets |= bit(two)
            for dst in iter_squares(targets):
                if rank_of(dst) == promo_rank:
                    moves.extend(Move(src, dst, kind) for kind in PROMOTION_PIECES)
                else:
                    moves.append(Move(src, dst))

    def _gen_castling(self, moves: list[Move], us: int, occupied: int) -> None:
        rights = self.castling & (
            (WHITE_KINGSIDE | WHITE_QUEENSIDE)
            if us == WHITE
            else (BLACK_KINGSIDE | BLACK_QUEENSIDE)
        )
        if not rights:
            return
        back = 0 if us == WHITE else 7
        king_sq = square(4, back)
        if self.mailbox[king_sq] != Piece(us, KING):
            return
        them = us ^ 1
        rook = Piece(us, ROOK)
        # (right flag, rook file, king destination file)
        for flag, rook_file, dest_file in (
            (WHITE_KINGSIDE if us == WHITE else BLACK_KINGSIDE, 7, 6),
            (WHITE_QUEENSIDE if us == WHITE else BLACK_QUEENSIDE, 0, 2),
        ):
            if not rights & flag:
                continue
            rook_sq = square(rook_file, back)
            if self.mailbox[rook_sq] != rook or BETWEEN[king_sq][rook_sq] & occupied:
                continue
            dest = square(dest_file, back)
            step = 1 if dest > king_sq else -1
            # The king may not castle out of, through, or into check.
            if any(self.is_attacked(s, them) for s in range(king_sq, dest + step, step)):
                continue
            moves.append(Move(king_sq, dest))

    # --- Make / unmake ---------------------------------------------------------

    def _put(self, sq: int, piece: Piece) -> None:
        self.pieces[piece.color][piece.kind] |= bit(sq)
        self.mailbox[sq] = piece

    def _remove(self, sq: int) -> Optional[Piece]:
        piece = self.mailbox[sq]
        if piece is not None:
            self.pieces[piece.color][piece.kind] &= ~bit(sq)
            self.mailbox[sq] = None
        return piece

    def is_capture(self, move: Move) -> bool:
        if self.mailbox[move.target] is not None:
            return True
        piece = self.mailbox[move.source]
        return piece is not None and piece.kind == PAWN and move.target == self.ep_square

    def is_castling(self, move: Move) -> bool:
        piece = self.mailbox[move.source]
        return piece is not None and self.is_castling_shape(piece, move)

    def push(self, move: Move) -> None:
        """Apply ``move`` without legality checks. Use :meth:`play` for validated moves."""
        piece = self.mailbox[move.source]
        if piece is None:
            raise ValueError(f"no piece on {square_name(move.source)}")

        self._history.append(
            (
                [list(p) for p in self.pieces],
                list(self.mailbox),
                self.turn,
                self.castling,
                self.ep_square,
                self.halfmove_clock,
                self.fullmove_number,
                len(self._repetitions),
            )
        )

        captured = self._remove(move.target)
        if piece.kind == PAWN and move.target == self.ep_square:
            captured = self._remove(move.target + (-8 if piece.color == WHITE else 8))

        self._remove(move.source)
        placed = Piece(piece.color, move.promotion) if move.promotion is not None else piece
        self._put(move.target, placed)

        if self.is_castling_shape(piece, move):
            back = rank_of(move.source)
            if move.target > move.source:
                self._put(square(5, back), self._remove(square(7, back)))
            else:
                self._put(square(3, back), self._remove(square(0, back)))

        self.castling &= ~(CASTLING_MASK[move.source] | CASTLING_MASK[move.target])
        self.ep_square = None
        if piece.kind == PAWN and abs(move.target - move.source) == 16:
            self.ep_square = (move.source + move.target) // 2

        if piece.kind == PAWN or captured is not None:
            self.halfmove_clock = 0
        else:
            self.halfmove_clock += 1
        if self.turn == BLACK:
            self.fullmove_number += 1
        self.turn ^= 1
        self._repetitions.append(self._position_key())

    @staticmethod
    def is_castling_shape(piece: Piece, move: Move) -> bool:
        return piece.kind == KING and abs(move.target - move.source) == 2

    def pop(self) -> None:
        """Undo the last :meth:`push`."""
        (
            pieces,
            mailbox,
            self.turn,
            self.castling,
            self.ep_square,
            self.halfmove_clock,
            self.fullmove_number,
            n_reps,
        ) = self._history.pop()
        self.pieces = pieces
        self.mailbox = mailbox
        del self._repetitions[n_reps:]

    def play(self, move: Move | str) -> Move:
        """Validate and apply a move given as a :class:`Move` or UCI string."""
        if isinstance(move, str):
            move = Move.from_uci(move)
        if not self.is_legal(move):
            raise ValueError(f"illegal move: {move.uci()} in {self.fen()}")
        self.push(move)
        return move

    # --- Game status -----------------------------------------------------------

    def _position_key(self) -> tuple:
        # En passant only counts if a capture is actually possible; keeping it
        # simple and conservative here is fine for repetition detection.
        return (tuple(tuple(p) for p in self.pieces), self.turn, self.castling, self.ep_square)

    def is_checkmate(self) -> bool:
        return self.is_check() and not self.legal_moves()

    def is_stalemate(self) -> bool:
        return not self.is_check() and not self.legal_moves()

    def is_insufficient_material(self) -> bool:
        for color in (WHITE, BLACK):
            p = self.pieces[color]
            if p[PAWN] or p[ROOK] or p[QUEEN]:
                return False
        minors = [popcount(self.pieces[c][KNIGHT] | self.pieces[c][BISHOP]) for c in (WHITE, BLACK)]
        if sum(minors) <= 1:
            return True
        # Only bishops left, all on the same colour of square.
        if not (self.pieces[WHITE][KNIGHT] | self.pieces[BLACK][KNIGHT]):
            bishops = self.pieces[WHITE][BISHOP] | self.pieces[BLACK][BISHOP]
            light = 0x55AA55AA55AA55AA
            return not bishops & light or not bishops & ~light
        return False

    def is_threefold_repetition(self) -> bool:
        return self._repetitions.count(self._repetitions[-1]) >= 3

    def outcome(self) -> Optional[Outcome]:
        if not self.legal_moves():
            return Outcome.CHECKMATE if self.is_check() else Outcome.STALEMATE
        if self.is_insufficient_material():
            return Outcome.INSUFFICIENT_MATERIAL
        if self.halfmove_clock >= 100:
            return Outcome.FIFTY_MOVES
        if self.is_threefold_repetition():
            return Outcome.THREEFOLD_REPETITION
        return None

    def winner(self) -> Optional[int]:
        """The winning colour if the game ended in checkmate, else ``None``."""
        return self.turn ^ 1 if self.is_checkmate() else None


def perft(board: ClassicalBoard, depth: int) -> int:
    """Count leaf nodes of the legal move tree; the standard move-generator test."""
    if depth == 0:
        return 1
    moves = board.legal_moves()
    if depth == 1:
        return len(moves)
    total = 0
    for move in moves:
        board.push(move)
        total += perft(board, depth - 1)
        board.pop()
    return total


__all__ = [
    "ClassicalBoard",
    "Move",
    "Piece",
    "Outcome",
    "perft",
    "STARTING_FEN",
    "PAWN",
    "KNIGHT",
    "BISHOP",
    "ROOK",
    "QUEEN",
    "KING",
    "WHITE",
    "BLACK",
]
