# PyInstaller spec for the desktop app. Build from the project root, after building the UI:
#
#     cd ui && npm ci && npm run build && cd ..
#     pip install -r requirements-desktop.txt
#     pyinstaller desktop/quantum_chess.spec --noconfirm
#
# Output: dist/QuantumChess/ (a folder with the QuantumChess executable; on macOS also
# dist/QuantumChess.app). The icons come from desktop/make_icon.py.

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent  # noqa: F821 (SPECPATH is defined by PyInstaller)
ICON = str(ROOT / "desktop" / ("icon.icns" if sys.platform == "darwin" else "icon.ico"))

if not (ROOT / "ui" / "dist" / "index.html").is_file():
    raise SystemExit("Build the UI first: cd ui && npm ci && npm run build")

hidden = (
    collect_submodules("cirq")  # cirq imports much of itself lazily
    + collect_submodules("uvicorn")  # protocol and loop implementations are chosen at runtime
    + collect_submodules("websockets")
    + ["api.server", "agent.levels", "agent.mcts"]
)

a = Analysis(  # noqa: F821
    [str(ROOT / "desktop" / "__main__.py")],
    pathex=[str(ROOT)],
    datas=[
        (str(ROOT / "ui" / "dist"), "ui/dist"),
        (str(ROOT / "desktop" / "icon.ico"), "desktop"),  # window icons (see desktop/app.py)
        (str(ROOT / "desktop" / "icon.png"), "desktop"),
    ]
    + collect_data_files("cirq"),
    hiddenimports=hidden,
    excludes=["matplotlib.tests", "pandas.tests", "scipy.tests", "numpy.tests", "tkinter"],
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="QuantumChess",
    console=False,
    icon=ICON,
)
coll = COLLECT(exe, a.binaries, a.datas, name="QuantumChess")  # noqa: F821

if sys.platform == "darwin":
    app = BUNDLE(  # noqa: F821
        coll,
        name="QuantumChess.app",
        icon=ICON,
        bundle_identifier="io.github.andreas-erick.quantum-chess",
        info_plist={"NSHighResolutionCapable": True},
    )
