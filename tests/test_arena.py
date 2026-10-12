"""The agent-vs-agent match runner."""

from agent.arena import match, play_game
from agent.mcts import MCTSAgent
from engine.bitboard import BLACK


def test_play_game_reports_result_from_a_point_of_view():
    a, b = MCTSAgent(iterations=5, seed=0), MCTSAgent(iterations=5, seed=1)
    record = play_game(a, b, seed=3, a_color=BLACK, max_plies=12)
    assert record.a_color == BLACK and 0 < record.plies <= 12
    assert record.a_score in (0.0, 0.5, 1.0)
    if record.winner is None:
        assert record.reason.startswith(("adjudicated", "fifty", "insufficient"))


def test_match_swaps_colours_and_scores():
    result = match(
        MCTSAgent(iterations=5), MCTSAgent(iterations=5), games=2, max_plies=8, workers=1
    )
    assert sorted(g.a_color for g in result.games) == [0, 1]
    assert 0.0 <= result.score <= 1.0
    assert "score" in result.summary()
