"""Release notes come from CHANGELOG.md (scripts/release_notes.py)."""

import importlib.util
from pathlib import Path

import pytest

from api import __version__

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "release_notes", ROOT / "scripts" / "release_notes.py"
)
release_notes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_notes)

CHANGELOG = """# Changelog

## [Unreleased]

## [1.1.0] - 2026-01-02

### Added
- Something new.

## [1.0.0] - 2026-01-01

First.

[1.1.0]: https://example.org/compare/v1.0.0...v1.1.0
"""


def test_takes_one_section_without_its_heading():
    assert release_notes.notes("v1.1.0", CHANGELOG) == "### Added\n- Something new.\n"
    assert release_notes.notes("1.0.0", CHANGELOG) == "First.\n"


def test_a_version_without_notes_fails():
    with pytest.raises(SystemExit, match="no section for 2.0.0"):
        release_notes.notes("2.0.0", CHANGELOG)


def test_the_current_version_has_notes():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert release_notes.notes(__version__, text).strip()
