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


def test_sequence_update_replaces_steps_without_breaking_rule_reference(
    repo: StudioRepository,
) -> None:
    project = repo.create_project("Classroom")
    human_pose = repo.create_human_pose(project.id, "Hands up", 0.78, 0.7)
    first_pose = repo.create_robot_pose(project.id, "Wave", {"r_sho_pitch": 0.4})
    second_pose = repo.create_robot_pose(project.id, "Bow", {"r_sho_pitch": -0.2})
    sequence = repo.create_sequence(
        project.id,
        "Greeting",
        [{"robot_pose_id": first_pose.id, "hold_ms": 700, "transition_ms": 300}],
    )
    rule = repo.create_behavior_rule(project.id, human_pose.id, sequence.id, 2.0)

    updated = repo.update_sequence(
        sequence.id,
        "Welcome",
        [
            {"robot_pose_id": second_pose.id, "hold_ms": 900, "transition_ms": 400},
            {"robot_pose_id": first_pose.id, "hold_ms": 500, "transition_ms": 200},
        ],
    )

    assert updated.id == sequence.id
    assert updated.created_at == sequence.created_at
    assert updated.name == "Welcome"
    assert [step.robot_pose_id for step in updated.steps] == [second_pose.id, first_pose.id]
    assert [(step.position, step.hold_ms, step.transition_ms) for step in updated.steps] == [
        (0, 900, 400),
        (1, 500, 200),
    ]
    assert repo.list_behavior_rules(project.id)[0].sequence_id == rule.sequence_id


def test_transaction_rolls_back_all_rows(repo: StudioRepository) -> None:
    with pytest.raises(RuntimeError), repo.transaction():
        repo.create_project("Will roll back")
        raise RuntimeError("stop")

    assert repo.list_projects() == []


def test_interactions_can_be_reordered_and_deleted_atomically(repo: StudioRepository) -> None:
    project = repo.create_project("Classroom")
    human_pose = repo.create_human_pose(project.id, "Hands up", 0.78, 0.7)
    robot_pose = repo.create_robot_pose(project.id, "Wave", {"r_sho_pitch": 0.4})
    sequences = [
        repo.create_sequence(
            project.id,
            f"__interaction_pose__:{index}",
            [{"robot_pose_id": robot_pose.id, "hold_ms": 700, "transition_ms": 300}],
        )
        for index in range(2)
    ]
    rules = [
        repo.create_behavior_rule(project.id, human_pose.id, sequence.id, 2.0)
        for sequence in sequences
    ]

    repo.reorder_interactions(project.id, [rules[1].id, rules[0].id])
    assert [rule.id for rule in repo.list_behavior_rules(project.id)] == [
        rules[1].id,
        rules[0].id,
    ]

    assert repo.delete_interaction(rules[1].id) is True
    assert [rule.id for rule in repo.list_behavior_rules(project.id)] == [rules[0].id]
    with pytest.raises(KeyError):
        repo.get_sequence(sequences[1].id)


def test_interaction_operations_ignore_lookalike_and_multistep_sequences(
    repo: StudioRepository,
) -> None:
    project = repo.create_project("Classroom")
    human = repo.create_human_pose(project.id, "Clap", 0.8, 0.7)
    robot = repo.create_robot_pose(project.id, "Wave", {"r_sho_roll": 15.0})
    direct = repo.create_sequence(
        project.id,
        "__interaction_pose__:direct",
        [{"robot_pose_id": robot.id, "hold_ms": 700, "transition_ms": 300}],
    )
    lookalike = repo.create_sequence(
        project.id,
        "xxinteractionXposeYY:not-direct",
        [{"robot_pose_id": robot.id, "hold_ms": 700, "transition_ms": 300}],
    )
    multistep = repo.create_sequence(
        project.id,
        "__interaction_pose__:multi",
        [
            {"robot_pose_id": robot.id, "hold_ms": 700, "transition_ms": 300},
            {"robot_pose_id": robot.id, "hold_ms": 700, "transition_ms": 300},
        ],
    )
    direct_rule = repo.create_behavior_rule(project.id, human.id, direct.id, 2)
    lookalike_rule = repo.create_behavior_rule(project.id, human.id, lookalike.id, 2)
    multistep_rule = repo.create_behavior_rule(project.id, human.id, multistep.id, 2)

    repo.reorder_interactions(project.id, [direct_rule.id])

    rules = {rule.id: rule for rule in repo.list_behavior_rules(project.id)}
    assert rules[direct_rule.id].priority == 1
    assert rules[lookalike_rule.id].priority == 0
    assert rules[multistep_rule.id].priority == 0
    with pytest.raises(ValueError, match="not a direct interaction"):
        repo.delete_interaction(multistep_rule.id)


def test_deleting_shared_interaction_keeps_its_referenced_sequence(
    repo: StudioRepository,
) -> None:
    project = repo.create_project("Classroom")
    human = repo.create_human_pose(project.id, "Clap", 0.8, 0.7)
    robot = repo.create_robot_pose(project.id, "Wave", {"r_sho_roll": 15.0})
    sequence = repo.create_sequence(
        project.id,
        "__interaction_pose__:shared",
        [{"robot_pose_id": robot.id, "hold_ms": 700, "transition_ms": 300}],
    )
    first = repo.create_behavior_rule(project.id, human.id, sequence.id, 2)
    second = repo.create_behavior_rule(project.id, human.id, sequence.id, 2)

    assert repo.delete_interaction(first.id) is True

    assert [rule.id for rule in repo.list_behavior_rules(project.id)] == [second.id]
    assert repo.get_sequence(sequence.id).id == sequence.id
