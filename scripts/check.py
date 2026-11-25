"""Run the checks CI runs, in the same order, and stop at the first failure.

    python scripts/check.py            # everything: Python, then the UI
    python scripts/check.py --python   # only lint, types and tests for the Python code
    python scripts/check.py --ui       # only the UI's lint, tests and build

A script rather than a Makefile so it works the same on Windows, macOS and Linux. Run it from
the activated virtual environment, with `npm ci` done in `ui/`.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent

# Keep these in step with .github/workflows/ci.yml.
PYTHON_CHECKS = [
    ["ruff", "check", "."],
    ["ruff", "format", "--check", "."],
    ["mypy"],
    ["pytest", "-q", "--cov", "--cov-report=term-missing:skip-covered"],
]
UI_CHECKS = [
    ["npm", "run", "lint"],
    ["npm", "test"],
    ["npm", "run", "build"],
]


def run(command: list[str], cwd: Path) -> bool:
    """Run one check and report it; True if it passed."""
    # On Windows, npm is npm.cmd: resolve it so no shell is needed.
    executable = shutil.which(command[0])
    if executable is None:
        print(f"\nFAILED: {command[0]} not found (activate the venv, or install Node.js)")
        return False
    print(f"\n> {' '.join(command)}", flush=True)
    started = time.monotonic()
    passed = subprocess.run([executable, *command[1:]], cwd=cwd).returncode == 0
    mark = "passed" if passed else "FAILED"
    print(f"{mark}: {' '.join(command)} ({time.monotonic() - started:.1f} s)", flush=True)
    return passed


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    only = parser.add_mutually_exclusive_group()
    only.add_argument("--python", action="store_true", help="only the Python checks")
    only.add_argument("--ui", action="store_true", help="only the UI checks")
    args = parser.parse_args(argv)

    plan = []
    if not args.ui:
        plan += [(command, ROOT) for command in PYTHON_CHECKS]
    if not args.python:
        plan += [(command, ROOT / "ui") for command in UI_CHECKS]
    for command, cwd in plan:
        if not run(command, cwd):
            return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
