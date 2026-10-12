"""Low-level bitboard primitives.

Squares are numbered 0..63 with a1 = 0, b1 = 1, ..., h1 = 7, a2 = 8, ..., h8 = 63.
A bitboard is a Python ``int`` whose bit ``n`` is set when square ``n`` is in the set.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Literal

FULL = (1 << 64) - 1

FILE_NAMES = "abcdefgh"
RANK_NAMES = "12345678"

WHITE, BLACK = 0, 1
ColorName = Literal["white", "black"]
COLOR_NAMES: tuple[ColorName, ColorName] = ("white", "black")

PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING = range(6)
PIECE_SYMBOLS = "pnbrqk"


def square(file: int, rank: int) -> int:
    return rank * 8 + file


def file_of(sq: int) -> int:
    return sq & 7


def rank_of(sq: int) -> int:
    return sq >> 3


def square_name(sq: int) -> str:
    return FILE_NAMES[file_of(sq)] + RANK_NAMES[rank_of(sq)]


def parse_square(name: str) -> int:
    if len(name) != 2 or name[0] not in FILE_NAMES or name[1] not in RANK_NAMES:
        raise ValueError(f"invalid square name: {name!r}")
    return square(FILE_NAMES.index(name[0]), RANK_NAMES.index(name[1]))


def bit(sq: int) -> int:
    return 1 << sq


def popcount(bb: int) -> int:
    return bb.bit_count()


def lsb(bb: int) -> int:
    """Index of the least significant set bit. ``bb`` must be non-zero."""
    return (bb & -bb).bit_length() - 1


def msb(bb: int) -> int:
    """Index of the most significant set bit. ``bb`` must be non-zero."""
    return bb.bit_length() - 1


def iter_squares(bb: int) -> Iterator[int]:
    while bb:
        low = bb & -bb
        yield low.bit_length() - 1
        bb ^= low


FILE_A = 0x0101010101010101
FILE_H = FILE_A << 7
RANK_1 = 0xFF
RANK_2 = RANK_1 << 8
RANK_4 = RANK_1 << 24
RANK_5 = RANK_1 << 32
RANK_7 = RANK_1 << 48
RANK_8 = RANK_1 << 56


# --- Precomputed attack tables -------------------------------------------------


def _step_table(deltas: list[tuple[int, int]]) -> list[int]:
    table = []
    for sq in range(64):
        f, r = file_of(sq), rank_of(sq)
        bb = 0
        for df, dr in deltas:
            nf, nr = f + df, r + dr
            if 0 <= nf < 8 and 0 <= nr < 8:
                bb |= bit(square(nf, nr))
        table.append(bb)
    return table


KNIGHT_ATTACKS = _step_table(
    [(1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1), (-2, 1), (-1, 2)]
)
KING_ATTACKS = _step_table([(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)])
PAWN_ATTACKS = (
    _step_table([(-1, 1), (1, 1)]),  # squares attacked by a white pawn
    _step_table([(-1, -1), (1, -1)]),  # squares attacked by a black pawn
)

# Ray directions as (file delta, rank delta). "Positive" directions increase the
# square index, so the nearest blocker on such a ray is the lowest set bit.
ORTHOGONAL = [(0, 1), (1, 0), (0, -1), (-1, 0)]
DIAGONAL = [(1, 1), (-1, 1), (1, -1), (-1, -1)]


def _ray_table(df: int, dr: int) -> list[int]:
    table = []
    for sq in range(64):
        f, r = file_of(sq) + df, rank_of(sq) + dr
        bb = 0
        while 0 <= f < 8 and 0 <= r < 8:
            bb |= bit(square(f, r))
            f, r = f + df, r + dr
        table.append(bb)
    return table


RAYS = {d: _ray_table(*d) for d in ORTHOGONAL + DIAGONAL}


def _is_positive(direction: tuple[int, int]) -> bool:
    df, dr = direction
    return dr > 0 or (dr == 0 and df > 0)


def _slider_attacks(sq: int, occupied: int, directions: list[tuple[int, int]]) -> int:
    attacks = 0
    for d in directions:
        ray = RAYS[d][sq]
        blockers = ray & occupied
        if blockers:
            first = lsb(blockers) if _is_positive(d) else msb(blockers)
            ray ^= RAYS[d][first]
        attacks |= ray
    return attacks


def rook_attacks(sq: int, occupied: int) -> int:
    return _slider_attacks(sq, occupied, ORTHOGONAL)


def bishop_attacks(sq: int, occupied: int) -> int:
    return _slider_attacks(sq, occupied, DIAGONAL)


def queen_attacks(sq: int, occupied: int) -> int:
    return rook_attacks(sq, occupied) | bishop_attacks(sq, occupied)


def _between_table() -> list[list[int]]:
    """``BETWEEN[a][b]`` is the set of squares strictly between a and b on a line."""
    table = [[0] * 64 for _ in range(64)]
    for a in range(64):
        for d in ORTHOGONAL + DIAGONAL:
            path = 0
            for b in (
                iter_squares(RAYS[d][a])
                if _is_positive(d)
                else reversed(list(iter_squares(RAYS[d][a])))
            ):
                table[a][b] = path
                path |= bit(b)
    return table


BETWEEN = _between_table()


def to_string(bb: int) -> str:
    """Render a bitboard as an 8x8 grid (rank 8 at the top), for debugging."""
    rows = (
        " ".join("1" if bb & bit(square(f, r)) else "." for f in range(8)) for r in range(7, -1, -1)
    )
    return "\n".join(rows)
