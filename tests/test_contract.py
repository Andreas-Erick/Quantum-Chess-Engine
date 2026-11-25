"""Names that are listed in more than one place (Python, the JSON contract, the UI) must match."""

import re
from pathlib import Path
from typing import get_args

from agent.levels import DEFAULT_LEVEL, LEVELS, LevelName

ROOT = Path(__file__).resolve().parent.parent


def ts_list(name: str) -> set[str]:
    """The strings in `export const <name> = ["a", "b"] as const;` in ui/src/types.ts."""
    source = (ROOT / "ui" / "src" / "types.ts").read_text(encoding="utf-8")
    match = re.search(rf"export const {name} = \[([^\]]+)\] as const;", source)
    assert match, f"ui/src/types.ts has no list {name}"
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def test_ai_levels_are_named_the_same_everywhere():
    assert set(get_args(LevelName)) == set(LEVELS), "LevelName vs LEVELS in agent/levels.py"
    assert ts_list("LEVEL_NAMES") == set(LEVELS), "ui/src/types.ts LEVEL_NAMES vs agent/levels.py"
    assert DEFAULT_LEVEL in LEVELS
