"""SQLite-backed storage for user-saved robot poses."""

import json
import sqlite3
from datetime import datetime

from app.config import REPO_ROOT

_DB_PATH = REPO_ROOT / "data" / "poses.db"


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS saved_poses (
            name       TEXT PRIMARY KEY,
            joints_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def save_pose(name: str, joints: dict[str, float]) -> None:
    """Persist joint states (radians) under the given name, overwriting if it exists."""
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO saved_poses (name, joints_json, created_at) VALUES (?, ?, ?)",
            (name, json.dumps(joints), datetime.utcnow().isoformat()),
        )


def get_pose(name: str) -> dict[str, float] | None:
    """Return joint states (radians) for a saved pose, or None if not found."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT joints_json FROM saved_poses WHERE name = ? COLLATE NOCASE", (name,)
        ).fetchone()
        return json.loads(row[0]) if row else None
    finally:
        conn.close()


def list_pose_names() -> list[str]:
    """Return all saved pose names in alphabetical order."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT name FROM saved_poses ORDER BY name COLLATE NOCASE"
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


def clear_all_poses() -> None:
    """Delete all saved poses. Called on server startup so poses don't persist across runs."""
    with _connect() as conn:
        conn.execute("DELETE FROM saved_poses")
