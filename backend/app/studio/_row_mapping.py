"""Conversion from SQLite rows to immutable studio domain records."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence as SequenceValue

from app.studio.models import (
    BehaviorRule,
    HumanPose,
    PoseSample,
    Project,
    RobotPose,
    Sequence,
    SequenceStep,
)


def project_from_row(row: sqlite3.Row) -> Project:
    return Project(
        row["id"],
        row["name"],
        row["schema_version"],
        json.loads(row["settings_json"]),
        row["created_at"],
        row["updated_at"],
    )


def human_pose_from_row(row: sqlite3.Row) -> HumanPose:
    return HumanPose(
        row["id"],
        row["project_id"],
        row["name"],
        row["thumbnail_svg"],
        row["min_confidence"],
        row["hold_seconds"],
        bool(row["enabled"]),
        row["created_at"],
        row["updated_at"],
    )


def pose_sample_from_row(row: sqlite3.Row) -> PoseSample:
    return PoseSample(
        row["id"],
        row["human_pose_id"],
        json.loads(row["features_json"]),
        json.loads(row["weights_json"]),
        json.loads(row["mirror_metadata_json"]),
        json.loads(row["quality_json"]),
        row["created_at"],
    )


def robot_pose_from_row(row: sqlite3.Row) -> RobotPose:
    return RobotPose(
        row["id"],
        row["project_id"],
        row["name"],
        json.loads(row["joints_json"]),
        row["thumbnail_svg"],
        row["source"],
        json.loads(row["safety_json"]),
        row["created_at"],
        row["updated_at"],
    )


def sequence_from_rows(
    row: sqlite3.Row, step_rows: SequenceValue[sqlite3.Row]
) -> Sequence:
    steps = tuple(
        SequenceStep(
            step["id"],
            step["sequence_id"],
            step["robot_pose_id"],
            step["position"],
            step["hold_ms"],
            step["transition_ms"],
        )
        for step in step_rows
    )
    return Sequence(
        row["id"],
        row["project_id"],
        row["name"],
        steps,
        row["created_at"],
        row["updated_at"],
    )


def behavior_rule_from_row(row: sqlite3.Row) -> BehaviorRule:
    return BehaviorRule(
        row["id"],
        row["project_id"],
        row["human_pose_id"],
        row["sequence_id"],
        row["cooldown_seconds"],
        row["priority"],
        bool(row["enabled"]),
        row["created_at"],
        row["updated_at"],
    )
