# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the combined server/vision/speaker backend binary.

Onedir build (not onefile) — see .agents/docs/features/desktop-packaging.md
for why. Built with: `uv run pyinstaller packaging/backend.spec --clean --noconfirm`
(run from the repo root, with a bare `uv sync` — no --extra robot/smpl/reid —
so torch and friends are never on the import path for Analysis to find).

Relies on `pyinstaller-hooks-contrib` (dev dependency group) for mediapipe/
opencv/uvicorn hidden-import coverage. If a hidden-import or missing-data
error surfaces at runtime that contrib hooks don't cover, add a custom hook
under packaging/hooks/ and point hookspath at it below.
"""

import glob
import os

ROOT = os.path.dirname(os.path.abspath(SPECPATH))
SRC = os.path.join(ROOT, "src")

datas = []
datas += [(f, "vision/models") for f in glob.glob(os.path.join(SRC, "vision", "models", "*.task"))]
datas += [(f, "vision/models") for f in glob.glob(os.path.join(SRC, "vision", "models", "*.pt"))]
datas += [(f, "llm/prompts") for f in glob.glob(os.path.join(SRC, "llm", "prompts", "*.md"))]

# Whole AiNex MuJoCo asset tree (xml + meshes/), bundled at a location the
# sys.frozen branch in src/simulator/mujoco_sim.py knows to look for.
datas += Tree(os.path.join(ROOT, "assets", "ainex"), prefix="assets/ainex")

a = Analysis(
    [os.path.join(ROOT, "packaging", "backend_entry.py")],
    pathex=[SRC],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="backend",
)
