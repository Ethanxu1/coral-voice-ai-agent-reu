"""Validated, transactional JSON project import and export."""

from __future__ import annotations

import json
import math
import sqlite3
from typing import Any

from app.robot.servo_config import SERVO_ID_MAP
from app.studio.repository import StudioRepository
from app.studio.schemas import (
    BehaviorRulePayload,
    HumanPosePayload,
    PoseSamplePayload,
    ProjectPackage,
    ProjectPayload,
    ProjectSettings,
    RobotPosePayload,
    SequencePayload,
    SequenceStepPayload,
)


class PackageValidationError(ValueError):
    """Raised before or during an atomic package import."""


def export_package(repo: StudioRepository, project_id: str) -> ProjectPackage:
    project = repo.get_project(project_id)
    human_poses = repo.list_human_poses(project_id)
    robot_poses = repo.list_robot_poses(project_id)
    sequences = repo.list_sequences(project_id)
    rules = repo.list_behavior_rules(project_id)
    samples = [
        sample
        for pose in human_poses
        for sample in repo.list_pose_samples(pose.id)
    ]
    return ProjectPackage(
        schema_version=repo.SCHEMA_VERSION,
        project=ProjectPayload(
            id=project.id,
            name=project.name,
            schema_version=project.schema_version,
            created_at=project.created_at,
            updated_at=project.updated_at,
        ),
        human_poses=[HumanPosePayload(**_record_dict(item)) for item in human_poses],
        training_samples=[
            PoseSamplePayload(**_record_dict(item)) for item in samples
        ],
        robot_poses=[RobotPosePayload(**_record_dict(item)) for item in robot_poses],
        sequences=[
            SequencePayload(
                id=item.id,
                project_id=item.project_id,
                name=item.name,
                steps=[
                    SequenceStepPayload(
                        id=step.id,
                        robot_pose_id=step.robot_pose_id,
                        position=step.position,
                        hold_ms=step.hold_ms,
                        transition_ms=step.transition_ms,
                    )
                    for step in item.steps
                ],
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
            for item in sequences
        ],
        rules=[BehaviorRulePayload(**_record_dict(item)) for item in rules],
        settings=ProjectSettings(output_mode="simulator"),
    )


def import_package(repo: StudioRepository, package: ProjectPackage) -> str:
    _validate_package(package)
    try:
        with repo.transaction() as connection:
            _insert_package(connection, package)
    except sqlite3.IntegrityError as exc:
        raise PackageValidationError(f"Package conflicts with stored data: {exc}") from exc
    return package.project.id


def _validate_package(package: ProjectPackage) -> None:
    groups = {
        "human pose": [item.id for item in package.human_poses],
        "training sample": [item.id for item in package.training_samples],
        "robot pose": [item.id for item in package.robot_poses],
        "sequence": [item.id for item in package.sequences],
        "rule": [item.id for item in package.rules],
    }
    all_ids = [package.project.id]
    for label, identifiers in groups.items():
        if len(identifiers) != len(set(identifiers)):
            raise PackageValidationError(f"Duplicate {label} ID")
        all_ids.extend(identifiers)
    if len(all_ids) != len(set(all_ids)):
        raise PackageValidationError("IDs must be unique across the package")

    project_id = package.project.id
    if any(item.project_id != project_id for item in package.human_poses):
        raise PackageValidationError("Human pose references another project")
    if any(item.project_id != project_id for item in package.robot_poses):
        raise PackageValidationError("Robot pose references another project")
    if any(item.project_id != project_id for item in package.sequences):
        raise PackageValidationError("Sequence references another project")
    if any(item.project_id != project_id for item in package.rules):
        raise PackageValidationError("Rule references another project")

    human_ids = {item.id for item in package.human_poses}
    robot_ids = {item.id for item in package.robot_poses}
    sequence_ids = {item.id for item in package.sequences}
    for sample in package.training_samples:
        if sample.human_pose_id not in human_ids:
            raise PackageValidationError("Training sample references missing human pose")
        if len(sample.features) != len(sample.weights) or not sample.features:
            raise PackageValidationError("Training feature dimensions do not match")
        if not all(
            math.isfinite(value) for value in (*sample.features, *sample.weights)
        ):
            raise PackageValidationError("Training features must be finite")
    for pose in package.robot_poses:
        unknown = set(pose.joints) - set(SERVO_ID_MAP)
        if unknown:
            raise PackageValidationError(f"Unknown robot joints: {sorted(unknown)}")
        if not all(math.isfinite(value) for value in pose.joints.values()):
            raise PackageValidationError("Robot joint values must be finite")
    for sequence in package.sequences:
        positions = [step.position for step in sequence.steps]
        if positions != list(range(len(positions))):
            raise PackageValidationError("Sequence step positions must be contiguous")
        if any(step.robot_pose_id not in robot_ids for step in sequence.steps):
            raise PackageValidationError("Sequence references missing robot pose")
    for rule in package.rules:
        if rule.human_pose_id not in human_ids:
            raise PackageValidationError("Rule references missing human pose")
        if rule.sequence_id not in sequence_ids:
            raise PackageValidationError("Rule references missing sequence")


def _insert_package(connection: sqlite3.Connection, package: ProjectPackage) -> None:
    project = package.project
    settings = {"output_mode": "simulator"}
    connection.execute(
        """INSERT INTO projects
           (id, name, schema_version, settings_json, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            project.id,
            project.name,
            package.schema_version,
            json.dumps(settings),
            project.created_at,
            project.updated_at,
        ),
    )
    for pose in package.human_poses:
        connection.execute(
            """INSERT INTO human_poses VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                pose.id, pose.project_id, pose.name, pose.thumbnail_svg,
                pose.min_confidence, pose.hold_seconds, int(pose.enabled),
                pose.created_at, pose.updated_at,
            ),
        )
    for sample in package.training_samples:
        connection.execute(
            """INSERT INTO pose_samples VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                sample.id, sample.human_pose_id, json.dumps(sample.features),
                json.dumps(sample.weights), json.dumps(sample.mirror_metadata),
                json.dumps(sample.quality), sample.created_at,
            ),
        )
    for pose in package.robot_poses:
        connection.execute(
            """INSERT INTO robot_poses VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                pose.id, pose.project_id, pose.name, json.dumps(pose.joints),
                pose.thumbnail_svg, pose.source, json.dumps(pose.safety),
                pose.created_at, pose.updated_at,
            ),
        )
    for sequence in package.sequences:
        connection.execute(
            "INSERT INTO sequences VALUES (?, ?, ?, ?, ?)",
            (
                sequence.id, sequence.project_id, sequence.name,
                sequence.created_at, sequence.updated_at,
            ),
        )
        for step in sequence.steps:
            connection.execute(
                "INSERT INTO sequence_steps VALUES (?, ?, ?, ?, ?, ?)",
                (
                    step.id, sequence.id, step.robot_pose_id, step.position,
                    step.hold_ms, step.transition_ms,
                ),
            )
    for rule in package.rules:
        connection.execute(
            """INSERT INTO behavior_rules VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rule.id, rule.project_id, rule.human_pose_id, rule.sequence_id,
                rule.cooldown_seconds, rule.priority, int(rule.enabled),
                rule.created_at, rule.updated_at,
            ),
        )


def _record_dict(record: Any) -> dict[str, Any]:
    return {field: getattr(record, field) for field in record.__dataclass_fields__}
