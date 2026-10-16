"""SQLite persistence for Motion Block Studio.

Connections are intentionally short-lived. An explicit ``transaction`` keeps one
connection active for the current context so multi-row operations are atomic.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Mapping, Sequence as SequenceValue
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.studio._row_mapping import (
    behavior_rule_from_row,
    human_pose_from_row,
    pose_sample_from_row,
    project_from_row,
    robot_pose_from_row,
    sequence_from_rows,
)
from app.studio._schema import apply_schema
from app.studio.models import (
    BehaviorRule,
    DeleteResult,
    HumanPose,
    PoseSample,
    Project,
    RobotPose,
    Sequence,
    SequenceStep,
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


INTERACTION_SEQUENCE_PREFIX = "__interaction_pose__:"


class StudioRepository:
    """Migration-driven repository for projects and reusable motion blocks."""

    SCHEMA_VERSION = 1

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._active_connection: ContextVar[sqlite3.Connection | None] = ContextVar(
            f"studio_connection_{id(self)}", default=None
        )
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        active = self._active_connection.get()
        if active is not None:
            yield active
            return

        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Run repository calls in one atomic transaction."""
        if self._active_connection.get() is not None:
            raise RuntimeError("Nested studio repository transactions are not supported")

        connection = self._connect()
        token = self._active_connection.set(connection)
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            self._active_connection.reset(token)
            connection.close()

    def close(self) -> None:
        """Compatibility hook; ordinary repository connections close per operation."""
        active = self._active_connection.get()
        if active is not None:
            active.close()
            self._active_connection.set(None)

    def _migrate(self) -> None:
        with self._connection() as connection:
            apply_schema(connection, self.SCHEMA_VERSION, _now())

    def create_project(self, name: str) -> Project:
        item_id = str(uuid4())
        timestamp = _now()
        settings = {"output_mode": "simulator"}
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO projects
                   (id, name, schema_version, settings_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (item_id, name, self.SCHEMA_VERSION, _json(settings), timestamp, timestamp),
            )
        return Project(item_id, name, self.SCHEMA_VERSION, settings, timestamp, timestamp)

    def list_projects(self) -> list[Project]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM projects ORDER BY created_at, id"
            ).fetchall()
        return [project_from_row(row) for row in rows]

    def get_project(self, project_id: str) -> Project:
        return project_from_row(self._require("projects", project_id))

    def create_human_pose(
        self,
        project_id: str,
        name: str,
        min_confidence: float,
        hold_seconds: float,
        *,
        thumbnail_svg: str = "",
        enabled: bool = True,
    ) -> HumanPose:
        item_id = str(uuid4())
        timestamp = _now()
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO human_poses
                   (id, project_id, name, thumbnail_svg, min_confidence,
                    hold_seconds, enabled, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item_id,
                    project_id,
                    name,
                    thumbnail_svg,
                    min_confidence,
                    hold_seconds,
                    int(enabled),
                    timestamp,
                    timestamp,
                ),
            )
        return HumanPose(
            item_id,
            project_id,
            name,
            thumbnail_svg,
            min_confidence,
            hold_seconds,
            enabled,
            timestamp,
            timestamp,
        )

    def get_human_pose(self, pose_id: str) -> HumanPose:
        return human_pose_from_row(self._require("human_poses", pose_id))

    def list_human_poses(self, project_id: str) -> list[HumanPose]:
        return [
            human_pose_from_row(row)
            for row in self._rows_for_project("human_poses", project_id)
        ]

    def create_pose_sample(
        self,
        human_pose_id: str,
        features: SequenceValue[float],
        weights: SequenceValue[float],
        *,
        mirror_metadata: Mapping[str, Any] | None = None,
        quality: Mapping[str, Any] | None = None,
    ) -> PoseSample:
        item_id = str(uuid4())
        timestamp = _now()
        mirror = dict(mirror_metadata or {})
        metrics = dict(quality or {})
        feature_values = list(features)
        weight_values = list(weights)
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO pose_samples
                   (id, human_pose_id, features_json, weights_json,
                    mirror_metadata_json, quality_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    item_id,
                    human_pose_id,
                    _json(feature_values),
                    _json(weight_values),
                    _json(mirror),
                    _json(metrics),
                    timestamp,
                ),
            )
        return PoseSample(
            item_id,
            human_pose_id,
            feature_values,
            weight_values,
            mirror,
            metrics,
            timestamp,
        )

    def list_pose_samples(self, human_pose_id: str) -> list[PoseSample]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM pose_samples WHERE human_pose_id = ? ORDER BY created_at, id",
                (human_pose_id,),
            ).fetchall()
        return [pose_sample_from_row(row) for row in rows]

    def create_robot_pose(
        self,
        project_id: str,
        name: str,
        joints: Mapping[str, float],
        *,
        thumbnail_svg: str = "",
        source: str = "simulator",
        safety: Mapping[str, Any] | None = None,
    ) -> RobotPose:
        item_id = str(uuid4())
        timestamp = _now()
        joint_values = dict(joints)
        safety_result = dict(safety or {})
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO robot_poses
                   (id, project_id, name, joints_json, thumbnail_svg, source,
                    safety_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item_id,
                    project_id,
                    name,
                    _json(joint_values),
                    thumbnail_svg,
                    source,
                    _json(safety_result),
                    timestamp,
                    timestamp,
                ),
            )
        return RobotPose(
            item_id,
            project_id,
            name,
            joint_values,
            thumbnail_svg,
            source,
            safety_result,
            timestamp,
            timestamp,
        )

    def get_robot_pose(self, pose_id: str) -> RobotPose:
        return robot_pose_from_row(self._require("robot_poses", pose_id))

    def list_robot_poses(self, project_id: str) -> list[RobotPose]:
        return [
            robot_pose_from_row(row)
            for row in self._rows_for_project("robot_poses", project_id)
        ]

    def create_sequence(
        self,
        project_id: str,
        name: str,
        steps: SequenceValue[Mapping[str, Any]],
    ) -> Sequence:
        sequence_id = str(uuid4())
        timestamp = _now()
        created_steps: list[SequenceStep] = []
        with self.transaction():
            with self._connection() as connection:
                connection.execute(
                    """INSERT INTO sequences
                       (id, project_id, name, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (sequence_id, project_id, name, timestamp, timestamp),
                )
                for position, step in enumerate(steps):
                    step_id = str(uuid4())
                    robot_pose_id = str(step["robot_pose_id"])
                    hold_ms = int(step.get("hold_ms", 500))
                    transition_ms = int(step.get("transition_ms", 250))
                    connection.execute(
                        """INSERT INTO sequence_steps
                           (id, sequence_id, robot_pose_id, position, hold_ms,
                            transition_ms) VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            step_id,
                            sequence_id,
                            robot_pose_id,
                            position,
                            hold_ms,
                            transition_ms,
                        ),
                    )
                    created_steps.append(
                        SequenceStep(
                            step_id,
                            sequence_id,
                            robot_pose_id,
                            position,
                            hold_ms,
                            transition_ms,
                        )
                    )
        return Sequence(
            sequence_id,
            project_id,
            name,
            tuple(created_steps),
            timestamp,
            timestamp,
        )

    def get_sequence(self, sequence_id: str) -> Sequence:
        row = self._require("sequences", sequence_id)
        with self._connection() as connection:
            step_rows = connection.execute(
                """SELECT * FROM sequence_steps WHERE sequence_id = ?
                   ORDER BY position""",
                (sequence_id,),
            ).fetchall()
        return sequence_from_rows(row, step_rows)

    def update_sequence(
        self,
        sequence_id: str,
        name: str,
        steps: SequenceValue[Mapping[str, Any]],
    ) -> Sequence:
        self._require("sequences", sequence_id)
        timestamp = _now()
        with self.transaction():
            with self._connection() as connection:
                connection.execute(
                    "UPDATE sequences SET name = ?, updated_at = ? WHERE id = ?",
                    (name, timestamp, sequence_id),
                )
                connection.execute(
                    "DELETE FROM sequence_steps WHERE sequence_id = ?",
                    (sequence_id,),
                )
                for position, step in enumerate(steps):
                    connection.execute(
                        """INSERT INTO sequence_steps
                           (id, sequence_id, robot_pose_id, position, hold_ms,
                            transition_ms) VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            str(uuid4()),
                            sequence_id,
                            str(step["robot_pose_id"]),
                            position,
                            int(step.get("hold_ms", 500)),
                            int(step.get("transition_ms", 250)),
                        ),
                    )
        return self.get_sequence(sequence_id)

    def list_sequences(self, project_id: str) -> list[Sequence]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM sequences WHERE project_id = ? ORDER BY created_at, id",
                (project_id,),
            ).fetchall()
            return [
                sequence_from_rows(
                    row,
                    connection.execute(
                        """SELECT * FROM sequence_steps WHERE sequence_id = ?
                           ORDER BY position""",
                        (row["id"],),
                    ).fetchall(),
                )
                for row in rows
            ]

    def create_behavior_rule(
        self,
        project_id: str,
        human_pose_id: str,
        sequence_id: str,
        cooldown_seconds: float,
        *,
        priority: int = 0,
        enabled: bool = True,
    ) -> BehaviorRule:
        item_id = str(uuid4())
        timestamp = _now()
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO behavior_rules
                   (id, project_id, human_pose_id, sequence_id, cooldown_seconds,
                    priority, enabled, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item_id,
                    project_id,
                    human_pose_id,
                    sequence_id,
                    cooldown_seconds,
                    priority,
                    int(enabled),
                    timestamp,
                    timestamp,
                ),
            )
        return BehaviorRule(
            item_id,
            project_id,
            human_pose_id,
            sequence_id,
            cooldown_seconds,
            priority,
            enabled,
            timestamp,
            timestamp,
        )

    def list_behavior_rules(self, project_id: str) -> list[BehaviorRule]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT * FROM behavior_rules WHERE project_id = ?
                   ORDER BY priority DESC, created_at, id""",
                (project_id,),
            ).fetchall()
        return [behavior_rule_from_row(row) for row in rows]

    def reorder_interactions(self, project_id: str, rule_ids: list[str]) -> None:
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("Interaction order contains duplicate rules")
        with self.transaction() as connection:
            rows = connection.execute(
                """SELECT behavior_rules.id
                   FROM behavior_rules
                   JOIN sequences ON sequences.id = behavior_rules.sequence_id
                   WHERE behavior_rules.project_id = ?
                     AND substr(sequences.name, 1, ?) = ?
                     AND (SELECT COUNT(*) FROM sequence_steps
                          WHERE sequence_id = sequences.id) = 1""",
                (project_id, len(INTERACTION_SEQUENCE_PREFIX), INTERACTION_SEQUENCE_PREFIX),
            ).fetchall()
            existing_ids = {row["id"] for row in rows}
            if existing_ids != set(rule_ids):
                raise ValueError("Interaction order is stale")
            timestamp = _now()
            for index, rule_id in enumerate(rule_ids):
                connection.execute(
                    """UPDATE behavior_rules SET priority = ?, updated_at = ?
                       WHERE id = ? AND project_id = ?""",
                    (len(rule_ids) - index, timestamp, rule_id, project_id),
                )

    def delete_interaction(self, rule_id: str) -> bool:
        with self.transaction() as connection:
            row = connection.execute(
                """SELECT behavior_rules.sequence_id, sequences.name,
                          (SELECT COUNT(*) FROM sequence_steps
                           WHERE sequence_id = sequences.id) AS step_count
                   FROM behavior_rules
                   JOIN sequences ON sequences.id = behavior_rules.sequence_id
                   WHERE behavior_rules.id = ?""",
                (rule_id,),
            ).fetchone()
            if row is None:
                return False
            if (
                not row["name"].startswith(INTERACTION_SEQUENCE_PREFIX)
                or row["step_count"] != 1
            ):
                raise ValueError("Rule is not a direct interaction")
            connection.execute("DELETE FROM behavior_rules WHERE id = ?", (rule_id,))
            remaining_references = connection.execute(
                "SELECT COUNT(*) FROM behavior_rules WHERE sequence_id = ?",
                (row["sequence_id"],),
            ).fetchone()[0]
            if remaining_references == 0:
                connection.execute("DELETE FROM sequences WHERE id = ?", (row["sequence_id"],))
        return True

    def delete_robot_pose(self, pose_id: str) -> DeleteResult:
        with self._connection() as connection:
            dependents = [
                row["sequence_id"]
                for row in connection.execute(
                    """SELECT DISTINCT sequence_id FROM sequence_steps
                       WHERE robot_pose_id = ? ORDER BY sequence_id""",
                    (pose_id,),
                ).fetchall()
            ]
            if dependents:
                return DeleteResult(False, dependents)
            cursor = connection.execute("DELETE FROM robot_poses WHERE id = ?", (pose_id,))
        return DeleteResult(cursor.rowcount > 0, [])

    def delete_human_pose(self, pose_id: str) -> DeleteResult:
        return self._protected_delete(
            "human_poses", pose_id, "behavior_rules", "human_pose_id"
        )

    def delete_sequence(self, sequence_id: str) -> DeleteResult:
        return self._protected_delete(
            "sequences", sequence_id, "behavior_rules", "sequence_id"
        )

    def export_rows(self, project_id: str) -> dict[str, list[dict[str, Any]]]:
        """Return JSON-compatible raw rows for a complete project export."""
        with self._connection() as connection:
            project = connection.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchall()
            human_poses = connection.execute(
                "SELECT * FROM human_poses WHERE project_id = ? ORDER BY created_at, id",
                (project_id,),
            ).fetchall()
            pose_ids = [row["id"] for row in human_poses]
            samples: list[sqlite3.Row] = []
            if pose_ids:
                placeholders = ",".join("?" for _ in pose_ids)
                samples = connection.execute(
                    f"SELECT * FROM pose_samples WHERE human_pose_id IN ({placeholders}) "
                    "ORDER BY created_at, id",
                    pose_ids,
                ).fetchall()
            robot_poses = connection.execute(
                "SELECT * FROM robot_poses WHERE project_id = ? ORDER BY created_at, id",
                (project_id,),
            ).fetchall()
            sequences = connection.execute(
                "SELECT * FROM sequences WHERE project_id = ? ORDER BY created_at, id",
                (project_id,),
            ).fetchall()
            sequence_ids = [row["id"] for row in sequences]
            steps: list[sqlite3.Row] = []
            if sequence_ids:
                placeholders = ",".join("?" for _ in sequence_ids)
                steps = connection.execute(
                    f"SELECT * FROM sequence_steps WHERE sequence_id IN ({placeholders}) "
                    "ORDER BY sequence_id, position",
                    sequence_ids,
                ).fetchall()
            rules = connection.execute(
                "SELECT * FROM behavior_rules WHERE project_id = ? ORDER BY created_at, id",
                (project_id,),
            ).fetchall()
        return {
            "projects": [dict(row) for row in project],
            "human_poses": [dict(row) for row in human_poses],
            "pose_samples": [dict(row) for row in samples],
            "robot_poses": [dict(row) for row in robot_poses],
            "sequences": [dict(row) for row in sequences],
            "sequence_steps": [dict(row) for row in steps],
            "behavior_rules": [dict(row) for row in rules],
        }

    def _protected_delete(
        self, table: str, item_id: str, dependent_table: str, foreign_key: str
    ) -> DeleteResult:
        allowed_tables = {"human_poses", "sequences"}
        allowed_dependencies = {
            ("behavior_rules", "human_pose_id"),
            ("behavior_rules", "sequence_id"),
        }
        if table not in allowed_tables or (dependent_table, foreign_key) not in allowed_dependencies:
            raise ValueError("Unsupported protected delete")
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT id FROM {dependent_table} WHERE {foreign_key} = ? ORDER BY id",
                (item_id,),
            ).fetchall()
            dependents = [row["id"] for row in rows]
            if dependents:
                return DeleteResult(False, dependents)
            cursor = connection.execute(f"DELETE FROM {table} WHERE id = ?", (item_id,))
        return DeleteResult(cursor.rowcount > 0, [])

    def _require(self, table: str, item_id: str) -> sqlite3.Row:
        allowed = {"projects", "human_poses", "robot_poses", "sequences"}
        if table not in allowed:
            raise ValueError(f"Unsupported table: {table}")
        with self._connection() as connection:
            row = connection.execute(
                f"SELECT * FROM {table} WHERE id = ?", (item_id,)
            ).fetchone()
        if row is None:
            raise KeyError(item_id)
        return row

    def _rows_for_project(self, table: str, project_id: str) -> list[sqlite3.Row]:
        allowed = {"human_poses", "robot_poses", "behavior_rules"}
        if table not in allowed:
            raise ValueError(f"Unsupported table: {table}")
        with self._connection() as connection:
            return connection.execute(
                f"SELECT * FROM {table} WHERE project_id = ? ORDER BY created_at, id",
                (project_id,),
            ).fetchall()

