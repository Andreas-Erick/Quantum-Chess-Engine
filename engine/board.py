"""QuantumBoard: chess rules over a partly classical, partly quantum position.

Every square carries a classical *label*: the piece that would be there if the square is
occupied. A square whose occupancy is certain lives on the classical board only. A square
whose occupancy is uncertain is also a qubit in the sparse :class:`QuantumRegister`.

Rules in this phase:

* **Jump** (``e2e4``): an ordinary move. A superposed piece moving to an empty square carries
  its amplitude along (iSWAP) without being measured.
* **Split** (``b1^a3c3``): a non-pawn piece moves to two empty squares at once, 50/50.
* **Merge** (``a3c3^b1``): two superposed parts of the same kind of piece recombine.
* **Measurement** happens when a move needs to know whether a square is occupied: capturing
  or entering a superposed square, or capturing *with* a superposed piece. If the outcome makes
  the move impossible (the attacker was not there, or the target turned out to be your own
  piece), the move fails and the turn still passes.
* There is no check: a game is won by capturing the enemy king. En passant is not supported.
* Sliding pieces cannot yet pass through superposed squares (Phase 3 adds entangling slides).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Optional

from engine.bitboard import (
    BETWEEN,
    BLACK,
    KING,
    KING_ATTACKS,
    KNIGHT,
    KNIGHT_ATTACKS,
    PAWN,
    PAWN_ATTACKS,
    QUEEN,
    WHITE,
    BISHOP,
    ROOK,
    bishop_attacks,
    bit,
    file_of,
    iter_squares,
    rank_of,
    rook_attacks,
    square,
    square_name,
)
from engine.classical import (
    BLACK_KINGSIDE,
    BLACK_QUEENSIDE,
    CASTLING_MASK,
    PROMOTION_PIECES,
    STARTING_FEN,
    WHITE_KINGSIDE,
    WHITE_QUEENSIDE,
    ClassicalBoard,
    Piece,
)
from engine.measurement import Measurement, ProbabilityResolver, RandomSource
from engine.moves import MoveType, QuantumMove, jump_ops, merge_ops, split_ops
from engine.register import QuantumRegister, square_qubit


class IllegalMoveError(ValueError):
    pass


@dataclass
class MoveResult:
    move: QuantumMove
    executed: bool  # False when a measurement made the move impossible
    measurements: list[Measurement] = field(default_factory=list)
    captured: Optional[Piece] = None
    winner: Optional[int] = None


class QuantumBoard:
    def __init__(self, fen: str = STARTING_FEN, rng: Optional[RandomSource] = None) -> None:
        classical = ClassicalBoard(fen)
        self.labels: list[Optional[Piece]] = list(classical.mailbox)
        self.turn = classical.turn
        self.castling = classical.castling
        self.fullmove_number = classical.fullmove_number
        self.register = QuantumRegister()
        self.resolver = ProbabilityResolver(rng)
        self.winner: Optional[int] = None
        self.history: list[MoveResult] = []

    # --- Queries ---------------------------------------------------------------------

    def piece_at(self, sq: int) -> Optional[Piece]:
        """The piece that may be on ``sq`` (see :meth:`probability` for how likely)."""
        return self.labels[sq]

    def is_classical(self, sq: int) -> bool:
        return sq not in self.register

    def probability(self, sq: int) -> float:
        if sq in self.register:
            return self.register.probability(sq)
        return 1.0 if self.labels[sq] is not None else 0.0

    def probabilities(self) -> list[float]:
        """Occupancy probability of every square, indexed a1 = 0 ... h8 = 63."""
        return [self.probability(sq) for sq in range(64)]

    def _labelled(self) -> int:
        return sum(bit(sq) for sq, p in enumerate(self.labels) if p is not None)

    def _certainly_own(self, color: int) -> int:
        return sum(
            bit(sq)
            for sq, p in enumerate(self.labels)
            if p is not None and p.color == color and self.is_classical(sq)
        )

    # --- Move shape ------------------------------------------------------------------

    def reachable(self, src: int) -> int:
        """Bitboard of squares the piece on ``src`` may jump to, ignoring castling.

        Squares that are possibly occupied block sliding pieces. A target that might be
        occupied is allowed; whether the move succeeds is settled by measurement.
        """
        piece = self.labels[src]
        if piece is None:
            return 0
        blockers = self._labelled()
        not_own = ~self._certainly_own(piece.color)
        if piece.kind == PAWN:
            return self._pawn_targets(src, piece.color)
        if piece.kind == KNIGHT:
            return KNIGHT_ATTACKS[src] & not_own
        if piece.kind == KING:
            return KING_ATTACKS[src] & not_own
        attacks = 0
        if piece.kind in (BISHOP, QUEEN):
            attacks |= bishop_attacks(src, blockers)
        if piece.kind in (ROOK, QUEEN):
            attacks |= rook_attacks(src, blockers)
        return attacks & not_own

    def _pawn_targets(self, src: int, color: int) -> int:
        forward = 8 if color == WHITE else -8
        start_rank = 1 if color == WHITE else 6
        targets = 0
        for dst in iter_squares(PAWN_ATTACKS[color][src]):
            label = self.labels[dst]
            if label is not None and label.color != color:
                targets |= bit(dst)
        one = src + forward
        if 0 <= one < 64 and (self.labels[one] is None or not self.is_classical(one)):
            targets |= bit(one)
            two = one + forward
            if (
                rank_of(src) == start_rank
                and self.labels[one] is None
                and (self.labels[two] is None or not self.is_classical(two))
            ):
                targets |= bit(two)
        return targets

    def _castling_targets(self, color: int) -> int:
        back = 0 if color == WHITE else 7
        king_sq = square(4, back)
        if self.labels[king_sq] != Piece(color, KING) or not self.is_classical(king_sq):
            return 0
        sides = (
            ((WHITE_KINGSIDE, 7, 6), (WHITE_QUEENSIDE, 0, 2))
            if color == WHITE
            else ((BLACK_KINGSIDE, 7, 6), (BLACK_QUEENSIDE, 0, 2))
        )
        targets = 0
        for flag, rook_file, dest_file in sides:
            rook_sq = square(rook_file, back)
            if (
                self.castling & flag
                and self.labels[rook_sq] == Piece(color, ROOK)
                and self.is_classical(rook_sq)
                and not BETWEEN[king_sq][rook_sq] & self._labelled()
            ):
                targets |= bit(square(dest_file, back))
        return targets

    # --- Validation & generation -----------------------------------------------------

    def _own_piece(self, sq: int) -> Piece:
        piece = self.labels[sq]
        if piece is None or piece.color != self.turn:
            raise IllegalMoveError(f"no {('white', 'black')[self.turn]} piece on {square_name(sq)}")
        return piece

    def validate(self, move: QuantumMove) -> None:
        if self.winner is not None:
            raise IllegalMoveError("the game is over")
        piece = self._own_piece(move.source)

        if move.move_type is MoveType.JUMP:
            reach = self.reachable(move.source)
            if piece.kind == KING:
                reach |= self._castling_targets(piece.color)
            if not reach & bit(move.target):
                raise IllegalMoveError(f"{piece.symbol} cannot move to {square_name(move.target)}")
            promotes = piece.kind == PAWN and rank_of(move.target) in (0, 7)
            if move.promotion is not None and (
                not promotes or move.promotion not in PROMOTION_PIECES
            ):
                raise IllegalMoveError("invalid promotion")
            return

        if piece.kind == PAWN:
            raise IllegalMoveError("pawns cannot split or merge")

        if move.move_type is MoveType.SPLIT:
            if move.target == move.target2:
                raise IllegalMoveError("split targets must differ")
            reach = self.reachable(move.source)
            for t in (move.target, move.target2):
                if not reach & bit(t) or self.labels[t] is not None:
                    raise IllegalMoveError(f"cannot split onto {square_name(t)}")
            return

        # Merge
        if move.source == move.source2 or self.labels[move.source2] != piece:
            raise IllegalMoveError("merge needs two parts of the same kind of piece")
        if self.is_classical(move.source) or self.is_classical(move.source2):
            raise IllegalMoveError("both merge sources must be in superposition")
        common = self.reachable(move.source) & self.reachable(move.source2)
        if not common & bit(move.target) or self.labels[move.target] is not None:
            raise IllegalMoveError(f"cannot merge onto {square_name(move.target)}")

    def legal_moves(self) -> list[QuantumMove]:
        if self.winner is not None:
            return []
        moves: list[QuantumMove] = []
        superposed: dict[Piece, list[int]] = {}
        for src, piece in enumerate(self.labels):
            if piece is None or piece.color != self.turn:
                continue
            reach = self.reachable(src)
            jumps = reach | (self._castling_targets(piece.color) if piece.kind == KING else 0)
            for dst in iter_squares(jumps):
                if piece.kind == PAWN and rank_of(dst) in (0, 7):
                    moves.extend(QuantumMove.jump(src, dst, p) for p in PROMOTION_PIECES)
                else:
                    moves.append(QuantumMove.jump(src, dst))
            if piece.kind == PAWN:
                continue
            empty = [t for t in iter_squares(reach) if self.labels[t] is None]
            moves.extend(QuantumMove.split(src, a, b) for a, b in combinations(empty, 2))
            if not self.is_classical(src):
                superposed.setdefault(piece, []).append(src)
        for squares in superposed.values():
            for a, b in combinations(squares, 2):
                common = self.reachable(a) & self.reachable(b)
                moves.extend(
                    QuantumMove.merge(a, b, t)
                    for t in iter_squares(common)
                    if self.labels[t] is None
                )
        return moves

    # --- Execution -------------------------------------------------------------------

    def do_move(self, move: QuantumMove | str) -> MoveResult:
        if isinstance(move, str):
            move = QuantumMove.parse(move)
        self.validate(move)

        if move.move_type is MoveType.SPLIT:
            result = self._split(move)
        elif move.move_type is MoveType.MERGE:
            result = self._merge(move)
        else:
            result = self._jump(move)

        if result.executed:
            for sq in move.squares:
                self.castling &= ~CASTLING_MASK[sq]
        self._update_winner()
        result.winner = self.winner
        if self.turn == BLACK:
            self.fullmove_number += 1
        self.turn ^= 1
        self.history.append(result)
        return result

    def _activate(self, sq: int) -> None:
        if sq not in self.register:
            self.register.add(sq, self.labels[sq] is not None)

    def _release(self, released: dict[int, bool]) -> None:
        for sq, occupied in released.items():
            if not occupied:
                self.labels[sq] = None

    def _apply(self, ops) -> None:
        self.register.apply(ops)
        self._release(self.register.release_definite())

    def _measure(self, sq: int) -> Measurement:
        measurement = self.resolver.measure(self.register, sq)
        self._release(measurement.collapsed)
        return measurement

    def _split(self, move: QuantumMove) -> MoveResult:
        piece = self.labels[move.source]
        for sq in (move.source, move.target, move.target2):
            self._activate(sq)
        self.labels[move.target] = self.labels[move.target2] = piece
        q = square_qubit
        self._apply(split_ops(q(move.source), q(move.target), q(move.target2)))
        return MoveResult(move, executed=True)

    def _merge(self, move: QuantumMove) -> MoveResult:
        self._activate(move.target)
        self.labels[move.target] = self.labels[move.source]
        q = square_qubit
        self._apply(merge_ops(q(move.source), q(move.source2), q(move.target)))
        return MoveResult(move, executed=True)

    def _jump(self, move: QuantumMove) -> MoveResult:
        src, tgt = move.source, move.target
        piece = self.labels[src]
        result = MoveResult(move, executed=False)

        if piece.kind == KING and abs(tgt - src) == 2:
            back = rank_of(src)
            rook_from, rook_to = (
                (square(7, back), square(5, back))
                if tgt > src
                else (
                    square(0, back),
                    square(3, back),
                )
            )
            self.labels[rook_to], self.labels[rook_from] = self.labels[rook_from], None
            self.labels[tgt], self.labels[src] = piece, None
            result.executed = True
            return result

        diagonal_pawn = piece.kind == PAWN and file_of(src) != file_of(tgt)

        if self.labels[tgt] is not None and not self.is_classical(tgt):
            result.measurements.append(self._measure(tgt))
        if self.labels[src] is None:  # collapsed away by the measurement above
            return result

        target_piece = self.labels[tgt]
        if target_piece is None:
            if diagonal_pawn:  # nothing to capture after all
                return result
            self._move_piece(move)
            result.executed = True
            return result

        if target_piece.color == piece.color or (piece.kind == PAWN and not diagonal_pawn):
            return result  # blocked

        if not self.is_classical(src):
            measurement = self._measure(src)
            result.measurements.append(measurement)
            if not measurement.occupied:
                return result
        self.labels[tgt] = None
        self._move_piece(move)
        result.captured = target_piece
        result.executed = True
        return result

    def _move_piece(self, move: QuantumMove) -> None:
        """Move whatever amplitude is on ``source`` to the (certainly empty) target."""
        src, tgt = move.source, move.target
        piece = self.labels[src]
        if self.is_classical(src):
            if move.promotion is not None or (piece.kind == PAWN and rank_of(tgt) in (0, 7)):
                promotion = move.promotion if move.promotion is not None else QUEEN
                piece = Piece(piece.color, promotion)
            self.labels[tgt], self.labels[src] = piece, None
            return
        self._activate(tgt)
        self.labels[tgt] = piece
        self._apply(jump_ops(square_qubit(src), square_qubit(tgt)))

    def _update_winner(self) -> None:
        for color in (WHITE, BLACK):
            if Piece(color, KING) not in self.labels:
                self.winner = color ^ 1

    # --- Display ---------------------------------------------------------------------

    def __str__(self) -> str:
        rows = []
        for r in range(7, -1, -1):
            cells = []
            for f in range(8):
                sq = square(f, r)
                piece = self.labels[sq]
                if piece is None:
                    cells.append(" .  ")
                elif self.is_classical(sq):
                    cells.append(f" {piece.symbol}  ")
                else:
                    cells.append(f" {piece.symbol}{round(self.probability(sq) * 100):<2d}"[:4])
            rows.append(f"{r + 1} " + "".join(cells))
        rows.append("   " + "   ".join("abcdefgh"))
        return "\n".join(rows)
