# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the combined server/vision/speaker backend binary.

Onedir build (not onefile) — see .agents/docs/features/desktop-packaging.md
for why. Built with: `uv run pyinstaller packaging/backend.spec --clean --noconfirm`
(run from the repo root, with a bare `uv sync` — no --extra robot/smpl/reid —
so torch and friends are never on the import path for Analysis to find).

Relies on `pyinstaller-hooks-contrib` (dev dependency group) for mediapipe/
opencv/uvicorn hidden-import coverage, plus a hand-written hook for `glfw`
(packaging/hooks/hook-glfw.py — mujoco.viewer imports it, but its native
lib is loaded via custom runtime logic contrib hooks don't cover). If
another hidden-import or missing-data error surfaces, add a hook here too.
"""

import glob
import os

ROOT = os.path.dirname(os.path.abspath(SPECPATH))
SRC = os.path.join(ROOT, "backend", "app")

datas = []
datas += [(f, "vision/models") for f in glob.glob(os.path.join(SRC, "vision", "models", "*.task"))]
datas += [(f, "vision/models") for f in glob.glob(os.path.join(SRC, "vision", "models", "*.pt"))]
datas += [(f, "llm/prompts") for f in glob.glob(os.path.join(SRC, "llm", "prompts", "*.md"))]

# Whole AiNex MuJoCo asset tree (xml + meshes/), bundled at a location the
# sys.frozen branch in backend/app/simulator/mujoco_sim.py knows to look for.
# NOTE: Tree() returns 3-tuples (dest, src, typecode), not the 2-tuples
# (src, dest) Analysis(datas=...) expects — it must be added in COLLECT()
# below instead, not merged into this list.
ainex_tree = Tree(os.path.join(ROOT, "assets", "ainex"), prefix="assets/ainex")

a = Analysis(
    [os.path.join(ROOT, "packaging", "backend_entry.py")],
    pathex=[SRC],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[os.path.join(ROOT, "packaging", "hooks")],
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
    ainex_tree,
    strip=False,
    upx=False,
    name="backend",
)
