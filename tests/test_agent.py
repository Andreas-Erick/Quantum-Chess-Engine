"""Phase 4: evaluation heuristic, MCTS agent, board copy and replay."""

import numpy as np
import pytest

from agent.heuristics import WIN_SCORE, evaluate, win_probability
from agent.mcts import MCTSAgent
from engine.bitboard import BLACK, WHITE, parse_square
from engine.board import QuantumBoard


def sq(name: str) -> int:
    return parse_square(name)


# --- Heuristics ----------------------------------------------------------------------


def test_start_position_is_balanced():
    board = QuantumBoard()
    assert evaluate(board, WHITE) == pytest.approx(0.0)
    assert win_probability(board, WHITE) == pytest.approx(0.5)


def test_material_advantage_is_symmetric():
    board = QuantumBoard("4k3/8/8/8/8/8/8/3QK3 w - - 0 1")
    assert evaluate(board, WHITE) > 8
    assert evaluate(board, BLACK) == pytest.approx(-evaluate(board, WHITE))
    assert win_probability(board, WHITE) > 0.9


def test_split_piece_counts_by_probability():
    whole = QuantumBoard("4k3/8/8/8/8/8/8/1N2K3 w - - 0 1")
    split = whole.copy()
    split.do_move("b1^a3c3")
    # Same material, only placement terms differ.
    assert evaluate(split, WHITE) == pytest.approx(evaluate(whole, WHITE), abs=0.3)


def test_uncertain_king_is_penalised():
    board = QuantumBoard("4k3/p7/8/8/8/8/P7/4K3 w - - 0 1")
    before = evaluate(board, WHITE)
    board.do_move("e1^d1f1")
    assert evaluate(board, WHITE) < before


def test_decided_game_scores():
    board = QuantumBoard("4k3/8/8/8/8/8/8/4KQ2 w - - 0 1")
    for move in ["f1f8", "e8e7", "f8e7"]:
        board.do_move(move)
    assert evaluate(board, WHITE) == WIN_SCORE
    assert win_probability(board, BLACK) == 0.0


# --- Copy & replay -------------------------------------------------------------------


def test_copy_is_independent():
    board = QuantumBoard()
    board.do_move("g1^f3h3")
    clone = board.copy()
    clone.do_move("b8^a6c6")
    clone.do_move("f3h3^g1")
    assert board.probability(sq("f3")) == pytest.approx(0.5)
    assert board.turn == BLACK and len(board.history) == 1
    assert clone.probability(sq("g1")) == 1.0


def test_replay_reproduces_measurement_outcomes():
    board = QuantumBoard("4k3/8/8/4b3/4p3/8/8/1N2K3 w - - 0 1", rng=np.random.default_rng(7))
    for move in ["b1^a3c3", "e5c3"]:
        board.do_move(move)
    records = [(r.move.notation(), r.outcomes) for r in board.history]
    replayed = QuantumBoard.replay(board.initial_fen, records)
    assert replayed.labels == board.labels
    assert replayed.probabilities() == board.probabilities()


def test_replay_rejects_impossible_history():
    with pytest.raises(ValueError):
        QuantumBoard.replay("4k3/8/8/8/8/8/8/1N2K3 w - - 0 1", [("b1c3", [True])])


# --- MCTS ----------------------------------------------------------------------------


def test_takes_certain_king_capture_immediately():
    board = QuantumBoard("4k3/8/8/8/8/8/8/4KR2 w - - 0 1")
    board.do_move("f1f7")
    board.do_move("e8e7")  # king blunders next to the rook... no check rule
    result = MCTSAgent(iterations=50, seed=0).search(board)
    assert result.move.notation() == "f7e7"
    assert result.iterations == 0  # found without searching


def test_captures_free_queen():
    board = QuantumBoard("4k3/8/8/3q4/8/8/8/3RK3 w - - 0 1")
    assert MCTSAgent(iterations=200, seed=0).choose_move(board).notation() == "d1d5"


@pytest.mark.parametrize("seed", range(3))
def test_saves_attacked_queen(seed):
    # The black rook attacks the queen down the d-file. Leaving any part of the queen on the
    # file (d2..d7) risks losing it; capturing on d8 is fine.
    board = QuantumBoard("3rk3/8/8/8/8/8/8/3QK3 w - - 0 1")
    board.do_move(MCTSAgent(iterations=400, seed=seed).choose_move(board))
    exposed = sum(board.probability(sq(f"d{rank}")) for rank in range(1, 8))
    assert exposed == 0


def test_search_is_reproducible_and_leaves_board_untouched():
    board = QuantumBoard()
    board.do_move("g1^f3h3")
    snapshot = board.probabilities()
    first = MCTSAgent(iterations=60, seed=42).search(board)
    second = MCTSAgent(iterations=60, seed=42).search(board)
    assert first.move == second.move
    assert [s.visits for s in first.moves] == [s.visits for s in second.moves]
    assert board.probabilities() == snapshot and len(board.history) == 1


def test_returns_legal_move_with_stats():
    board = QuantumBoard()
    result = MCTSAgent(iterations=80, seed=1).search(board)
    assert result.move in board.legal_moves()
    assert sum(s.visits for s in result.moves) == 80
    assert all(0.0 <= s.value <= 1.0 for s in result.moves)


def test_time_limit_is_respected():
    board = QuantumBoard()
    result = MCTSAgent(iterations=10**6, time_limit=0.2, seed=0).search(board)
    assert result.elapsed < 1.0 and result.iterations < 10**6


def test_game_over_raises():
    board = QuantumBoard("4k3/8/8/8/8/8/8/4KQ2 w - - 0 1")
    for move in ["f1f8", "e8e7", "f8e7"]:
        board.do_move(move)
    with pytest.raises(ValueError):
        MCTSAgent(iterations=5).search(board)
