"""Game-ending rules: check warnings and draws."""

import pytest

from agent.heuristics import win_probability
from agent.mcts import MCTSAgent
from engine.bitboard import WHITE, parse_square
from engine.board import IllegalMoveError, QuantumBoard


def sq(name: str) -> int:
    return parse_square(name)


# --- Check -----------------------------------------------------------------------


def test_no_threats_at_start():
    assert QuantumBoard().king_threats() == {}


def test_rook_on_open_file_threatens_king():
    board = QuantumBoard("4r1k1/8/8/8/8/8/8/4K3 w - - 0 1")
    assert board.king_threats() == {sq("e1"): 1.0}
    assert board.king_threats(color=1) == {}


def test_threat_through_uncertain_square_still_counts():
    # The knight half on e2 may block the rook, but the rook could still try to slide through.
    board = QuantumBoard("4r1k1/8/8/8/8/8/8/2N1K3 w - - 0 1")
    board.do_move("c1^e2a2")
    board.do_move("g8h8")
    assert board.king_threats() == {sq("e1"): 1.0}


def test_threats_on_split_king_report_each_half():
    board = QuantumBoard("3r2k1/8/8/8/8/8/8/4K3 w - - 0 1")
    board.do_move("e1^d2f2")
    board.do_move("g8h8")
    threats = board.king_threats()
    assert threats == {sq("d2"): pytest.approx(0.5)}  # the rook on d8 cannot reach f2


# --- Draws -----------------------------------------------------------------------


def test_bare_kings_is_a_draw():
    board = QuantumBoard("4k3/8/8/8/8/8/4q3/4K3 w - - 0 1")
    board.do_move("e1e2")
    assert board.winner is None
    assert board.draw_reason == "insufficient material"
    assert board.is_over and board.legal_moves() == []
    with pytest.raises(IllegalMoveError):
        board.do_move("e2e3")


def test_fifty_move_rule():
    board = QuantumBoard("4k3/8/8/8/8/8/8/R3K3 w - - 98 1")
    board.do_move("a1a2")
    assert not board.is_over
    board.do_move("e8d8")
    assert board.draw_reason == "fifty-move rule"


@pytest.mark.parametrize("move", ["e2e3", "a1a8"])
def test_pawn_moves_and_captures_reset_the_clock(move):
    board = QuantumBoard("r3k3/8/8/8/8/8/4P3/R3K3 w - - 40 1")
    board.do_move(move)
    assert board.halfmove_clock == 0


def test_measurement_resets_the_clock():
    board = QuantumBoard("4k3/8/8/8/8/8/8/1N2K3 w - - 40 1", rng=None)
    board.do_move("b1^a3c3")
    assert board.halfmove_clock == 41  # quantum moves are reversible: no reset
    board.resolver.forced.append(False)
    board.do_move("e8e7")
    board.do_move("c3e4")  # moves with its uncertainty, no measurement
    assert board.halfmove_clock == 43
    board.resolver.forced.append(True)
    board.do_move("e7e6")
    board.do_move("e1e2")
    board.do_move("e6e5")
    board.do_move("e4c5")
    assert board.halfmove_clock == 47


def test_draw_survives_replay():
    board = QuantumBoard("4k3/8/8/8/8/8/8/R3K3 w - - 99 1")
    board.do_move("a1a2")
    records = [(r.move.notation(), r.outcomes) for r in board.history]
    assert QuantumBoard.replay(board.initial_fen, records).draw_reason == "fifty-move rule"


def test_agent_scores_draws_as_half_and_refuses_to_search():
    board = QuantumBoard("4k3/8/8/8/8/8/8/R3K3 w - - 99 1")
    board.do_move("a1a2")
    assert win_probability(board, WHITE) == 0.5
    with pytest.raises(ValueError):
        MCTSAgent(iterations=5, seed=0).search(board)
