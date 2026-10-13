"""scripts/bump_version.py sets the version in every file that has it."""

import importlib.util
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

spec = importlib.util.spec_from_file_location("bump_version", ROOT / "scripts" / "bump_version.py")
assert spec is not None and spec.loader is not None
bump_version = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bump_version)


def test_bump_rewrites_every_copy_with_lf_line_endings(tmp_path, monkeypatch):
    for name in bump_version.TARGETS:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / name, tmp_path / name)
    monkeypatch.setattr(bump_version, "ROOT", tmp_path)

    assert sorted(bump_version.bump("98.76.54")) == sorted(bump_version.TARGETS)
    for name in bump_version.TARGETS:
        data = (tmp_path / name).read_bytes()
        assert b"98.76.54" in data, name
        assert b"\r" not in data, f"{name} was written with CRLF line endings"
