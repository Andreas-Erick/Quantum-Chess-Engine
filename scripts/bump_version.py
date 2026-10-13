"""Set the release version everywhere it is written down.

    python scripts/bump_version.py 0.9.0

Updates pyproject.toml, api/__init__.py (the version the API reports), ui/package.json and
ui/package-lock.json. tests/test_version.py checks that they agree. See CONTRIBUTING.md for the
whole release process.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")

# File -> (pattern matching the current version line, replacement template), and how many
# occurrences there must be, so a changed file layout fails loudly instead of half-updating.
TARGETS = {
    "pyproject.toml": (r'^version = "[^"]+"$', 'version = "{v}"', 1),
    "api/__init__.py": (r'^__version__ = "[^"]+"$', '__version__ = "{v}"', 1),
    # The package's own version: the first "version" key in each file (the lock file repeats it
    # under packages[""]; dependencies' versions come later and are left alone).
    "ui/package.json": (r'^  "version": "[^"]+",$', '  "version": "{v}",', 1),
    "ui/package-lock.json": (r'^(  |      )"version": "[^"]+",$', r'\1"version": "{v}",', 2),
}


def bump(version: str) -> list[str]:
    if not SEMVER.match(version):
        raise SystemExit(f"Not a version like 1.2.3: {version!r}")
    changed = []
    for name, (pattern, template, count) in TARGETS.items():
        path = ROOT / name
        text = path.read_text(encoding="utf-8")
        regex = re.compile(pattern, re.MULTILINE)
        if name == "ui/package-lock.json":
            # Only the root entries: the top-level version and packages[""].version.
            head, sep, rest = text.partition('"dependencies"')
            new_head, n = regex.subn(template.format(v=version), head)
            text_new = new_head + sep + rest
        else:
            text_new, n = regex.subn(template.format(v=version), text, count=count)
        if n != count:
            raise SystemExit(f"{name}: expected {count} version line(s), found {n}")
        if text_new != text:
            # LF on every platform, as .gitattributes stores them (not CRLF on Windows).
            path.write_text(text_new, encoding="utf-8", newline="\n")
            changed.append(name)
    return changed


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    for name in bump(sys.argv[1]):
        print(f"updated {name}")
