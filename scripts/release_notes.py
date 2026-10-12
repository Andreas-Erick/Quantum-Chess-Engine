"""Print a release's notes: its section of CHANGELOG.md, without the heading.

    python scripts/release_notes.py 0.9.0      # or v0.9.0

The release workflow uses it for the GitHub release's description. Fails if the changelog has
no section for that version, so a release can't go out without notes.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"


def notes(version: str, text: str) -> str:
    version = version.removeprefix("v")
    heading = re.compile(rf"^## \[{re.escape(version)}\][^\n]*\n", re.MULTILINE)
    match = heading.search(text)
    if not match:
        raise SystemExit(f"CHANGELOG.md has no section for {version}")
    rest = text[match.end() :]
    end = re.search(r"^(## |\[[^\]]+\]: )", rest, re.MULTILINE)
    return (rest[: end.start()] if end else rest).strip() + "\n"


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    sys.stdout.write(notes(sys.argv[1], CHANGELOG.read_text(encoding="utf-8")))
