"""Names that are listed in more than one place (Python, the JSON contract, the UI) must match."""

import re
from pathlib import Path
from typing import get_args

from agent.levels import DEFAULT_LEVEL, LEVELS
from api.schemas import LevelName

ROOT = Path(__file__).resolve().parent.parent


def ts_union(name: str) -> set[str]:
    """The string members of `export type <name> = "a" | "b";` in ui/src/types.ts."""
    source = (ROOT / "ui" / "src" / "types.ts").read_text(encoding="utf-8")
    match = re.search(rf"export type {name} = ([^;]+);", source)
    assert match, f"ui/src/types.ts has no type {name}"
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def test_ai_levels_are_named_the_same_everywhere():
    assert set(get_args(LevelName)) == set(LEVELS), "api/schemas.py LevelName vs agent/levels.py"
    assert ts_union("LevelName") == set(LEVELS), "ui/src/types.ts LevelName vs agent/levels.py"
    assert DEFAULT_LEVEL in LEVELS
