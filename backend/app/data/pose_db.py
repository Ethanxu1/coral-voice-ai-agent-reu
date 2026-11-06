"""Postgres-backed storage for user-saved robot poses."""

import psycopg
from psycopg.types.json import Jsonb

from app.config import DATABASE_URL


def _connect() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL)


def init_db() -> None:
    """Create the saved_poses table if it doesn't exist yet."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS saved_poses (
                name       TEXT PRIMARY KEY,
                joints     JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )


def save_pose(name: str, joints: dict[str, float]) -> None:
    """Persist joint states (radians) under the given name, overwriting if it exists."""
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO saved_poses (name, joints) VALUES (%s, %s)
            ON CONFLICT (name) DO UPDATE SET joints = EXCLUDED.joints, created_at = now()
            """,
            (name, Jsonb(joints)),
        )


def get_pose(name: str) -> dict[str, float] | None:
    """Return joint states (radians) for a saved pose (case-insensitive), or None."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT joints FROM saved_poses WHERE lower(name) = lower(%s) LIMIT 1", (name,)
        ).fetchone()
    return row[0] if row else None


def list_pose_names() -> list[str]:
    """Return all saved pose names in case-insensitive alphabetical order."""
    with _connect() as conn:
        rows = conn.execute("SELECT name FROM saved_poses ORDER BY lower(name)").fetchall()
    return [r[0] for r in rows]


def clear_all_poses() -> None:
    """Delete all saved poses. Called on server startup so poses don't persist across runs."""
    with _connect() as conn:
        conn.execute("DELETE FROM saved_poses")
