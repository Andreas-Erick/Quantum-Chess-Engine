"""The layers import only downwards: engine <- agent <- api <- desktop (docs/architecture.md).

This keeps the engine usable on its own, and keeps the AI and the server swappable.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LAYERS = ("engine", "agent", "api", "desktop")
ALLOWED = {
    "engine": set(),
    "agent": {"engine"},
    "api": {"engine", "agent"},
    "desktop": {"api"},
}


def imported_layers(path: Path) -> set[str]:
    """The project layers a file imports, including imports inside functions."""
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        else:
            continue
        found |= {name.split(".")[0] for name in names} & set(LAYERS)
    return found


@pytest.mark.parametrize("layer", LAYERS)
def test_layers_import_only_the_layers_below(layer):
    for path in sorted((ROOT / layer).glob("*.py")):
        extra = imported_layers(path) - ALLOWED[layer] - {layer}
        assert not extra, f"{path.relative_to(ROOT)} imports {sorted(extra)}"


def test_the_check_sees_imports(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text("import os\nfrom api.server import x\n\ndef f():\n    import agent.mcts\n")
    assert imported_layers(sample) == {"api", "agent"}
