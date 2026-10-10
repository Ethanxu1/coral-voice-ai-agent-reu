"""Persistence contract tests for the Motion Block Studio repository."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.studio.repository import StudioRepository


@pytest.fixture
def repo(tmp_path: Path) -> StudioRepository:
    repository = StudioRepository(tmp_path / "studio.db")
    yield repository
    repository.close()


@pytest.fixture
def populated_sequence(repo: StudioRepository):
    project = repo.create_project("Classroom gestures")
    robot_pose = repo.create_robot_pose(
        project.id,
        "Wave start",
        {"r_sho_pitch": 0.5, "r_el_pitch": -0.4},
    )
    return repo.create_sequence(
        project.id,
        "Friendly wave",
        [
            {
                "robot_pose_id": robot_pose.id,
                "hold_ms": 500,
                "transition_ms": 250,
            }
        ],
    )


def test_data_survives_repository_reopen(tmp_path: Path) -> None:
    db = tmp_path / "studio.db"
    repo = StudioRepository(db)
    project = repo.create_project("Classroom gestures")
    pose = repo.create_human_pose(project.id, "Hands up", 0.78, 0.7)
    repo.close()

    reopened = StudioRepository(db)
    try:
        assert reopened.get_human_pose(pose.id).name == "Hands up"
    finally:
        reopened.close()


def test_referenced_robot_pose_delete_is_rejected(
    repo: StudioRepository, populated_sequence
) -> None:
    result = repo.delete_robot_pose(populated_sequence.steps[0].robot_pose_id)

    assert result.deleted is False
    assert result.dependents == [populated_sequence.id]


def test_transaction_rolls_back_all_rows(repo: StudioRepository) -> None:
    with pytest.raises(RuntimeError), repo.transaction():
        repo.create_project("Will roll back")
        raise RuntimeError("stop")

    assert repo.list_projects() == []
