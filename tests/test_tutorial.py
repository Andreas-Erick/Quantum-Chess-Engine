"""The UI tutorial's lessons (ui/src/tutorial/lessons.json) must stay playable on the engine."""

import json
from pathlib import Path

import numpy as np
import pytest

from engine.bitboard import parse_square
from engine.board import QuantumBoard

LESSONS = json.loads(
    (Path(__file__).resolve().parent.parent / "ui" / "src" / "tutorial" / "lessons.json").read_text(
        encoding="utf-8"
    )
)
# The move type a notation belongs to: e2e4, g1^f3h3, f3h3^g1.
MODE_OF = {
    "jump": lambda n: "^" not in n,
    "split": lambda n: n.find("^") == 2,
    "merge": lambda n: n.find("^") == 4,
}


def accepted(step: dict, board: QuantumBoard) -> list[str]:
    moves = [m.notation() for m in board.legal_moves()]
    return [m for m in moves if any(m.startswith(prefix) for prefix in step["accept"])]


def play_lesson(lesson: dict, seed: int = 0, pick=0) -> QuantumBoard:
    board = QuantumBoard(lesson["fen"], rng=np.random.default_rng(seed))
    for notation in lesson.get("setup", []):
        assert board.do_move(notation).executed
    for step in lesson["steps"]:
        options = accepted(step, board)
        assert options, f"{lesson['id']}: no legal move matches {step['accept']}"
        board.do_move(options[pick % len(options)])
        if "reply" in step:
            assert board.do_move(step["reply"]).executed
    return board


def prob(board: QuantumBoard, square: str) -> float:
    return board.probability(parse_square(square))


@pytest.mark.parametrize("lesson", LESSONS, ids=[lesson["id"] for lesson in LESSONS])
def test_every_step_is_playable_and_well_formed(lesson):
    assert lesson["steps"] and lesson["steps"][-1].get("explain")
    board = QuantumBoard(lesson["fen"])
    for notation in lesson.get("setup", []):
        board.do_move(notation)
    for step in lesson["steps"]:
        options = accepted(step, board)
        assert options and all(MODE_OF[step["mode"]](m) for m in options), step["prompt"]
        board.do_move(options[0])
        if "reply" in step:
            assert board.do_move(step["reply"]).executed


def test_lesson_ids_are_unique():
    ids = [lesson["id"] for lesson in LESSONS]
    assert len(ids) == len(set(ids))


def by_id(lesson_id: str) -> dict:
    return next(lesson for lesson in LESSONS if lesson["id"] == lesson_id)


def test_goal_lesson_wins():
    assert play_lesson(by_id("goal")).winner is not None


def test_check_lesson_starts_in_check_and_escapes():
    lesson = by_id("check")
    assert QuantumBoard(lesson["fen"]).king_threats()
    for pick in range(3):
        assert not play_lesson(lesson, pick=pick).king_threats()


def test_split_lesson_makes_two_halves():
    board = play_lesson(by_id("split"))
    halves = [p for p in board.probabilities() if 0 < p < 1]
    assert halves == pytest.approx([0.5, 0.5])


def test_merge_lesson_restores_the_knight():
    assert prob(play_lesson(by_id("merge")), "g1") == pytest.approx(1.0)


def test_split_again_lesson_makes_quarters():
    uncertain = sorted(p for p in play_lesson(by_id("split-again")).probabilities() if 0 < p < 1)
    assert uncertain == pytest.approx([0.25, 0.25, 0.5])


def test_measurement_lesson_collapses_either_way():
    lesson = by_id("measurement")
    board = QuantumBoard(lesson["fen"])
    board.do_move(lesson["setup"][0])
    assert board.king_threats()  # the 50% knight on d3 attacks e1
    outcomes = set()
    for seed in range(12):
        board = play_lesson(lesson, seed=seed)
        assert all(p in (0.0, 1.0) for p in board.probabilities())
        outcomes.add(prob(board, "d5"))
    assert outcomes == {0.0, 1.0}


def test_entanglement_lesson_entangles_queen_and_knight():
    board = play_lesson(by_id("entanglement"))
    assert prob(board, "h5") == pytest.approx(0.5) and prob(board, "d1") == pytest.approx(0.5)
    group = next(g for g in board.register.groups if parse_square("h5") in g)
    assert parse_square("f3") in group
