"""Static evaluation of a quantum position.

Every term is weighted by the probability that the piece is actually there, so a knight
split 50/50 counts as half a knight on each square. Material is the dominant term.

A *threat* term looks one capture ahead: the side to move is credited with most of the best
capture it has available (a hanging piece, a favourable trade, or the enemy king). Without it,
a search that stops in the middle of an exchange cannot tell a safe position from one where a
piece, or the game, is about to be lost.
"""

from __future__ import annotations

import math

from engine.bitboard import (
    BISHOP,
    KING,
    KING_ATTACKS,
    KNIGHT,
    KNIGHT_ATTACKS,
    PAWN,
    PAWN_ATTACKS,
    QUEEN,
    ROOK,
    WHITE,
    bishop_attacks,
    file_of,
    iter_squares,
    rank_of,
    rook_attacks,
)
from engine.board import QuantumBoard

PIECE_VALUES = {PAWN: 1.0, KNIGHT: 3.0, BISHOP: 3.2, ROOK: 5.0, QUEEN: 9.0, KING: 0.0}

CENTER_BONUS = 0.25  # per piece fully on d4/e4/d5/e5
NEAR_CENTER_BONUS = 0.1  # per piece fully on the 12 squares around them
PAWN_ADVANCE_BONUS = 0.05  # per rank advanced
KING_UNCERTAINTY_PENALTY = 1.5  # a king that is not certainly anywhere can be captured by luck

# What capturing the king is worth to the threat term: decisive, but discounted by how likely
# the king, the attacker and its path are to cooperate.
KING_THREAT_VALUE = 20.0
THREAT_WEIGHT = 0.4  # share of the best available capture credited to the side to move (tuned)

WIN_SCORE = 1000.0
SCORE_SCALE = 4.0  # pawns of advantage that map to roughly a 73% win probability


def _centrality(sq: int) -> float:
    f, r = file_of(sq), rank_of(sq)
    if 3 <= f <= 4 and 3 <= r <= 4:
        return CENTER_BONUS
    if 2 <= f <= 5 and 2 <= r <= 5:
        return NEAR_CENTER_BONUS
    return 0.0


def attacks(board: QuantumBoard, sq: int) -> int:
    """Squares the piece on ``sq`` attacks, own pieces included (so defence counts).

    Like the engine's slides, only certainly occupied squares block a line.
    """
    piece = board.piece_at(sq)
    if piece.kind == PAWN:
        return PAWN_ATTACKS[piece.color][sq]
    if piece.kind == KNIGHT:
        return KNIGHT_ATTACKS[sq]
    if piece.kind == KING:
        return KING_ATTACKS[sq]
    blockers = board._certainly_occupied()
    result = 0
    if piece.kind in (BISHOP, QUEEN):
        result |= bishop_attacks(sq, blockers)
    if piece.kind in (ROOK, QUEEN):
        result |= rook_attacks(sq, blockers)
    return result


def best_capture(board: QuantumBoard) -> float:
    """Expected material the side to move wins with its best single capture, in pawns.

    A defended target costs the attacker its own value in return. Every term is scaled by the
    probability that target and attacker are really there.
    """
    # cheapest[color][sq] = (value, probability) of color's least valuable attacker of sq
    cheapest: tuple[dict[int, tuple[float, float]], ...] = ({}, {})
    for src, piece in enumerate(board.labels):
        if piece is None:
            continue
        value = KING_THREAT_VALUE if piece.kind == KING else PIECE_VALUES[piece.kind]
        p = board.probability(src)
        table = cheapest[piece.color]
        for target in iter_squares(attacks(board, src)):
            if target not in table or value < table[target][0]:
                table[target] = (value, p)

    mover = board.turn
    best = 0.0
    for target, (attacker_value, attacker_p) in cheapest[mover].items():
        piece = board.piece_at(target)
        if piece is None or piece.color == mover:
            continue
        p = board.probability(target)
        if piece.kind == KING:
            gain = KING_THREAT_VALUE
        else:
            gain = PIECE_VALUES[piece.kind]
            if target in cheapest[mover ^ 1]:
                gain -= attacker_value
        best = max(best, gain * p * attacker_p)
    return best


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
    threat = THREAT_WEIGHT * best_capture(board)
    return score + threat if board.turn == color else score - threat


def win_probability(board: QuantumBoard, color: int = WHITE) -> float:
    """Map :func:`evaluate` onto [0, 1] for use as an MCTS reward."""
    if board.winner is not None:
        return 1.0 if board.winner == color else 0.0
    if board.draw_reason is not None:
        return 0.5
    return 0.5 + 0.5 * math.tanh(evaluate(board, color) / SCORE_SCALE)
