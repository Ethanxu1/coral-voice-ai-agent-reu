"""Resolves paths for bundled resources and writable app state, across both
dev and PyInstaller-frozen execution.
"""

import sys
from pathlib import Path


def repo_root() -> Path:
    """Project root in dev mode, or the PyInstaller bundle root when frozen.
    For read-only bundled resources (assets/, models, prompts) only — see
    user_data_dir() for anything the app writes to.

    This module lives at the flat src/ root (pyproject.toml's
    [tool.hatch.build.targets.wheel] sources=["src"]), so `Path(__file__)
    .parent.parent` from *here* is always the repo root in dev mode,
    regardless of how deep the calling module is nested under src/.
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).parent.parent


def user_data_dir() -> Path:
    """Writable location for state that must persist across launches (the
    saved-poses database, recordings) — separate from repo_root() because an
    installed app's bundle directory may not be writable (macOS .app
    bundles, Windows Program Files). Matches the existing
    ~/.coral/settings.json convention (src/server.py's VIEWER_SETTING_PATH).
    Unchanged in dev mode — still resolves under the repo root.
    """
    if getattr(sys, "frozen", False):
        return Path.home() / ".coral"
    return repo_root()
