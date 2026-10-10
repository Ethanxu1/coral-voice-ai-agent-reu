"""Versioned JSON project package tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.studio.import_export import (
    PackageValidationError,
    export_package,
    import_package,
)
from app.studio.repository import StudioRepository
from app.studio.schemas import ProjectPackage


def _seed(repo: StudioRepository):
    project = repo.create_project("Classroom")
    human = repo.create_human_pose(project.id, "Hands up", 0.78, 0.7)
    repo.create_pose_sample(human.id, [0.0, 1.0], [1.0, 1.0])
    robot = repo.create_robot_pose(
        project.id, "Wave", {"r_sho_pitch": 0.5}, safety={"safe": True}
    )
    sequence = repo.create_sequence(
        project.id,
        "Wave twice",
        [{"robot_pose_id": robot.id, "hold_ms": 300, "transition_ms": 250}],
    )
    repo.create_behavior_rule(project.id, human.id, sequence.id, 2.0)
    return project


def test_import_with_dangling_reference_rolls_back(tmp_path: Path) -> None:
    repo = StudioRepository(tmp_path / "source.db")
    project = _seed(repo)
    before = export_package(repo, project.id).model_dump(mode="json")
    broken = {
        **before,
        "rules": [
            {
                **before["rules"][0],
                "human_pose_id": "missing",
            }
        ],
    }

    with pytest.raises(PackageValidationError, match="human pose"):
        import_package(repo, ProjectPackage.model_validate(broken))

    assert export_package(repo, project.id).model_dump(mode="json") == before


def test_export_import_round_trip_forces_simulator_mode(tmp_path: Path) -> None:
    source = StudioRepository(tmp_path / "source.db")
    project = _seed(source)
    payload = export_package(source, project.id).model_dump(mode="json")
    payload["settings"]["output_mode"] = "live_robot"
    destination = StudioRepository(tmp_path / "destination.db")

    imported_id = import_package(destination, ProjectPackage.model_validate(payload))
    exported = export_package(destination, imported_id)

    assert len(exported.training_samples) == 1
    assert len(exported.sequences[0].steps) == 1
    assert exported.settings.output_mode == "simulator"
