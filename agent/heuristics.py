"""Static evaluation of a quantum position.

Every term is weighted by the probability that the piece is actually there, so a knight
split 50/50 counts as half a knight on each square. Material is the dominant term.
"""

from __future__ import annotations

import math

from engine.bitboard import BISHOP, KING, KNIGHT, PAWN, QUEEN, ROOK, WHITE, file_of, rank_of
from engine.board import QuantumBoard

PIECE_VALUES = {PAWN: 1.0, KNIGHT: 3.0, BISHOP: 3.2, ROOK: 5.0, QUEEN: 9.0, KING: 0.0}

CENTER_BONUS = 0.25  # per piece fully on d4/e4/d5/e5
NEAR_CENTER_BONUS = 0.1  # per piece fully on the 12 squares around them
PAWN_ADVANCE_BONUS = 0.05  # per rank advanced
KING_UNCERTAINTY_PENALTY = 1.5  # a king that is not certainly anywhere can be captured by luck

WIN_SCORE = 1000.0
SCORE_SCALE = 4.0  # pawns of advantage that map to roughly a 73% win probability


def _centrality(sq: int) -> float:
    f, r = file_of(sq), rank_of(sq)
    if 3 <= f <= 4 and 3 <= r <= 4:
        return CENTER_BONUS
    if 2 <= f <= 5 and 2 <= r <= 5:
        return NEAR_CENTER_BONUS
    return 0.0


def evaluate(board: QuantumBoard, color: int = WHITE) -> float:
    """Score in pawns from ``color``'s point of view; +/-WIN_SCORE once the game is decided."""
    if board.winner is not None:
        return WIN_SCORE if board.winner == color else -WIN_SCORE
    if board.draw_reason is not None:
        return 0.0

    score = 0.0
    for sq, piece in enumerate(board.labels):
        if piece is None:
            continue
        p = board.probability(sq)
        value = PIECE_VALUES[piece.kind]
        if piece.kind != KING:
            value += _centrality(sq)
        if piece.kind == PAWN:
            advanced = rank_of(sq) - 1 if piece.color == WHITE else 6 - rank_of(sq)
            value += PAWN_ADVANCE_BONUS * advanced
        elif piece.kind == KING and p < 1.0:
            # Each uncertain king square is a chance for the opponent to land a capture.
            value -= KING_UNCERTAINTY_PENALTY * (1.0 - p)
        score += p * value if piece.color == color else -p * value
    return score


def win_probability(board: QuantumBoard, color: int = WHITE) -> float:
    """Map :func:`evaluate` onto [0, 1] for use as an MCTS reward."""
    if board.winner is not None:
        return 1.0 if board.winner == color else 0.0
    if board.draw_reason is not None:
        return 0.5
    return 0.5 + 0.5 * math.tanh(evaluate(board, color) / SCORE_SCALE)
