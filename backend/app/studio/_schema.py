"""SQLite schema migration helpers for Motion Block Studio."""

from __future__ import annotations

import sqlite3


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    schema_version INTEGER NOT NULL,
    settings_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS human_poses (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL COLLATE NOCASE,
    thumbnail_svg TEXT NOT NULL DEFAULT '',
    min_confidence REAL NOT NULL,
    hold_seconds REAL NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, name)
);
CREATE INDEX IF NOT EXISTS idx_human_poses_project ON human_poses(project_id);

CREATE TABLE IF NOT EXISTS pose_samples (
    id TEXT PRIMARY KEY,
    human_pose_id TEXT NOT NULL REFERENCES human_poses(id) ON DELETE CASCADE,
    features_json TEXT NOT NULL,
    weights_json TEXT NOT NULL,
    mirror_metadata_json TEXT NOT NULL,
    quality_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pose_samples_human_pose ON pose_samples(human_pose_id);

CREATE TABLE IF NOT EXISTS robot_poses (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL COLLATE NOCASE,
    joints_json TEXT NOT NULL,
    thumbnail_svg TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL,
    safety_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, name)
);
CREATE INDEX IF NOT EXISTS idx_robot_poses_project ON robot_poses(project_id);

CREATE TABLE IF NOT EXISTS sequences (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL COLLATE NOCASE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, name)
);
CREATE INDEX IF NOT EXISTS idx_sequences_project ON sequences(project_id);

CREATE TABLE IF NOT EXISTS sequence_steps (
    id TEXT PRIMARY KEY,
    sequence_id TEXT NOT NULL REFERENCES sequences(id) ON DELETE CASCADE,
    robot_pose_id TEXT NOT NULL REFERENCES robot_poses(id) ON DELETE RESTRICT,
    position INTEGER NOT NULL,
    hold_ms INTEGER NOT NULL,
    transition_ms INTEGER NOT NULL,
    UNIQUE(sequence_id, position)
);
CREATE INDEX IF NOT EXISTS idx_sequence_steps_sequence ON sequence_steps(sequence_id);
CREATE INDEX IF NOT EXISTS idx_sequence_steps_robot_pose ON sequence_steps(robot_pose_id);

CREATE TABLE IF NOT EXISTS behavior_rules (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    human_pose_id TEXT NOT NULL REFERENCES human_poses(id) ON DELETE RESTRICT,
    sequence_id TEXT NOT NULL REFERENCES sequences(id) ON DELETE RESTRICT,
    cooldown_seconds REAL NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_behavior_rules_project ON behavior_rules(project_id);
CREATE INDEX IF NOT EXISTS idx_behavior_rules_human_pose ON behavior_rules(human_pose_id);
CREATE INDEX IF NOT EXISTS idx_behavior_rules_sequence ON behavior_rules(sequence_id);
"""


def apply_schema(
    connection: sqlite3.Connection, schema_version: int, applied_at: str
) -> None:
    """Apply idempotent schema version 1 and record it."""
    connection.executescript(SCHEMA_SQL)
    connection.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
        (schema_version, applied_at),
    )
