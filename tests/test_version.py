"""The release version is written in several files; they must agree."""

import json
import re
from pathlib import Path

from api import __version__
from api.server import create_app

ROOT = Path(__file__).resolve().parent.parent


def test_every_copy_of_the_version_agrees():
    pyproject = re.search(r'^version = "([^"]+)"$', (ROOT / "pyproject.toml").read_text(), re.M)
    package = json.loads((ROOT / "ui" / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "ui" / "package-lock.json").read_text(encoding="utf-8"))
    versions = {
        "pyproject.toml": pyproject.group(1),
        "api/__init__.py": __version__,
        "ui/package.json": package["version"],
        "ui/package-lock.json": lock["version"],
        'ui/package-lock.json packages[""]': lock["packages"][""]["version"],
    }
    assert len(set(versions.values())) == 1, versions


def test_the_api_reports_the_release_version():
    assert create_app(ui_dir=None).version == __version__
