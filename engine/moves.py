"""Quantum move types, their notation, and the unitaries that implement them.

All gates come from the iSWAP family, which conserves the number of |1> qubits: pieces can be
spread across squares, but never created or destroyed by a unitary. Only measurement plus a
capture removes a piece.

Notation (as in Cantwell's Quantum Chess):
    jump   ``e2e4``    (``e7e8q`` for promotion)
    split  ``b1^a3c3`` (one source, two targets)
    merge  ``a3c3^b1`` (two sources, one target)
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import cirq

from engine.bitboard import PIECE_SYMBOLS, parse_square, square_name

SQRT_ISWAP = cirq.ISWAP**0.5
SQRT_ISWAP_INV = cirq.ISWAP**-0.5


class MoveType(Enum):
    JUMP = "jump"
    SPLIT = "split"
    MERGE = "merge"


@dataclass(frozen=True)
class QuantumMove:
    move_type: MoveType
    source: int
    target: int
    source2: Optional[int] = None  # second source of a merge
    target2: Optional[int] = None  # second target of a split
    promotion: Optional[int] = None

    @classmethod
    def jump(cls, source: int, target: int, promotion: Optional[int] = None) -> QuantumMove:
        return cls(MoveType.JUMP, source, target, promotion=promotion)

    @classmethod
    def split(cls, source: int, target: int, target2: int) -> QuantumMove:
        return cls(MoveType.SPLIT, source, target, target2=target2)

    @classmethod
    def merge(cls, source: int, source2: int, target: int) -> QuantumMove:
        return cls(MoveType.MERGE, source, target, source2=source2)

    @property
    def split_targets(self) -> tuple[int, int]:
        """A split's two targets. Raises ``ValueError`` for any other move."""
        if self.move_type is not MoveType.SPLIT or self.target2 is None:
            raise ValueError(f"a {self.move_type.value} move has no split targets")
        return self.target, self.target2

    @property
    def merge_sources(self) -> tuple[int, int]:
        """A merge's two sources. Raises ``ValueError`` for any other move."""
        if self.move_type is not MoveType.MERGE or self.source2 is None:
            raise ValueError(f"a {self.move_type.value} move has no merge sources")
        return self.source, self.source2

    @property
    def squares(self) -> tuple[int, ...]:
        return tuple(
            s for s in (self.source, self.source2, self.target, self.target2) if s is not None
        )

    def notation(self) -> str:
        if self.move_type is MoveType.SPLIT:
            t1, t2 = self.split_targets
            return f"{square_name(self.source)}^{square_name(t1)}{square_name(t2)}"
        if self.move_type is MoveType.MERGE:
            s1, s2 = self.merge_sources
            return f"{square_name(s1)}{square_name(s2)}^{square_name(self.target)}"
        promo = PIECE_SYMBOLS[self.promotion] if self.promotion is not None else ""
        return square_name(self.source) + square_name(self.target) + promo

    def __str__(self) -> str:
        return self.notation()

    @classmethod
    def parse(cls, text: str) -> QuantumMove:
        text = text.strip()
        try:
            if "^" in text:
                left, right = text.split("^")
                if len(left) == 2 and len(right) == 4:
                    return cls.split(
                        parse_square(left), parse_square(right[:2]), parse_square(right[2:])
                    )
                if len(left) == 4 and len(right) == 2:
                    return cls.merge(
                        parse_square(left[:2]), parse_square(left[2:]), parse_square(right)
                    )
            elif len(text) in (4, 5):
                promo = None
                if len(text) == 5:
                    if text[4] not in "nbrq":
                        raise ValueError
                    promo = PIECE_SYMBOLS.index(text[4])
                return cls.jump(parse_square(text[:2]), parse_square(text[2:4]), promo)
        except ValueError:
            pass
        raise ValueError(f"invalid quantum move notation: {text!r}")


# --- Unitaries ----------------------------------------------------------------------


def jump_ops(source: cirq.Qid, target: cirq.Qid) -> list[cirq.Operation]:
    """Move a piece onto an empty square: a full iSWAP."""
    return [cirq.ISWAP(source, target)]


def split_ops(source: cirq.Qid, target: cirq.Qid, target2: cirq.Qid) -> list[cirq.Operation]:
    """Send a piece to two squares at once with equal amplitude.

    sqrt(iSWAP) acts as a 50/50 beam splitter between source and the first target; a full
    iSWAP then moves the half left on the source to the second target:
    |1,0,0> -> (i|0,1,0> + i|0,0,1>) / sqrt(2).
    """
    return [SQRT_ISWAP(source, target), cirq.ISWAP(source, target2)]


def merge_ops(source: cirq.Qid, source2: cirq.Qid, target: cirq.Qid) -> list[cirq.Operation]:
    """The inverse of a split: recombine two halves of a piece onto one square.

    Recombination is complete only when the halves have the phases a split produces; other
    phases interfere only partially and leave some amplitude on the sources.
    """
    return [(cirq.ISWAP**-1)(source2, target), SQRT_ISWAP_INV(source, target)]


def slide_ops(source: cirq.Qid, target: cirq.Qid, path: Sequence[cirq.Qid]) -> list[cirq.Operation]:
    """Move a piece through possibly occupied squares: an iSWAP controlled on an empty path.

    In every branch where some path square is occupied, the piece stays put. This entangles
    the moving piece with the blockers.
    """
    if not path:
        return jump_ops(source, target)
    return [cirq.ISWAP(source, target).controlled_by(*path, control_values=[0] * len(path))]
