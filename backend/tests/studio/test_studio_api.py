"""HTTP contracts for Motion Block Studio."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.studio import configure_studio, router
from app.studio.repository import StudioRepository
from app.studio.runtime import StudioRuntime
from app.studio.sequence_player import PlaybackResult


@pytest.fixture
def repo(tmp_path: Path) -> StudioRepository:
    return StudioRepository(tmp_path / "studio.db")


@pytest.fixture
def client(repo: StudioRepository):
    configure_studio(repo, StudioRuntime.disabled(repo))
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as test_client:
        yield test_client


def test_live_output_defaults_to_simulator(client: TestClient) -> None:
    assert client.get("/studio/output-mode").json() == {"mode": "simulator"}


def test_trigger_mode_requires_an_explicit_start(client: TestClient) -> None:
    assert client.get("/studio/trigger-mode").json() == {"enabled": False}

    response = client.put("/studio/trigger-mode", json={"enabled": True})

    assert response.status_code == 200
    assert response.json() == {"enabled": True}


def test_project_and_human_pose_crud(client: TestClient) -> None:
    project = client.post("/studio/projects", json={"name": "Classroom"}).json()
    response = client.post(
        "/studio/human-poses",
        json={
            "project_id": project["id"],
            "name": "Hands up",
            "min_confidence": 0.78,
            "hold_seconds": 0.7,
        },
    )

    assert response.status_code == 201
    assert client.get(
        "/studio/human-poses", params={"project_id": project["id"]}
    ).json()[0]["name"] == "Hands up"

    deleted = client.delete(f"/studio/human-poses/{response.json()['id']}")

    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True}
    assert client.get(
        "/studio/human-poses", params={"project_id": project["id"]}
    ).json() == []


def test_sequence_can_be_deleted_when_it_has_no_rule_dependents(
    client: TestClient, repo: StudioRepository
) -> None:
    project = repo.create_project("Classroom")
    pose = repo.create_robot_pose(project.id, "Wave", {"l_sho_pitch": 0.4})
    sequence = repo.create_sequence(
        project.id,
        "Temporary response",
        [{"robot_pose_id": pose.id, "hold_ms": 700, "transition_ms": 300}],
    )

    response = client.delete(f"/studio/sequences/{sequence.id}")

    assert response.status_code == 200
    assert response.json() == {"deleted": True}
    assert repo.list_sequences(project.id) == []


def test_sequence_can_be_updated_in_place(
    client: TestClient, repo: StudioRepository
) -> None:
    project = repo.create_project("Classroom")
    pose = repo.create_robot_pose(project.id, "Wave", {"l_sho_pitch": 0.4})
    sequence = repo.create_sequence(
        project.id,
        "Greeting",
        [{"robot_pose_id": pose.id, "hold_ms": 700, "transition_ms": 300}],
    )

    response = client.put(
        f"/studio/sequences/{sequence.id}",
        json={
            "name": "Updated greeting",
            "steps": [
                {"robot_pose_id": pose.id, "hold_ms": 900, "transition_ms": 450}
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["id"] == sequence.id
    assert response.json()["name"] == "Updated greeting"
    assert response.json()["steps"][0]["hold_ms"] == 900
    assert repo.get_sequence(sequence.id).steps[0].transition_ms == 450


def test_sequence_update_reports_name_conflict_without_changing_sequence(
    client: TestClient, repo: StudioRepository
) -> None:
    project = repo.create_project("Classroom")
    pose = repo.create_robot_pose(project.id, "Wave", {"l_sho_pitch": 0.4})
    repo.create_sequence(
        project.id,
        "Greeting",
        [{"robot_pose_id": pose.id, "hold_ms": 700, "transition_ms": 300}],
    )
    sequence = repo.create_sequence(
        project.id,
        "Farewell",
        [{"robot_pose_id": pose.id, "hold_ms": 500, "transition_ms": 250}],
    )

    response = client.put(
        f"/studio/sequences/{sequence.id}",
        json={
            "name": "Greeting",
            "steps": [{"robot_pose_id": pose.id, "hold_ms": 900, "transition_ms": 450}],
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Name already exists"}
    assert repo.get_sequence(sequence.id).name == "Farewell"
    assert repo.get_sequence(sequence.id).steps[0].hold_ms == 500


def test_sequence_update_rejects_missing_pose_and_rolls_back(
    client: TestClient, repo: StudioRepository
) -> None:
    project = repo.create_project("Classroom")
    pose = repo.create_robot_pose(project.id, "Wave", {"l_sho_pitch": 0.4})
    sequence = repo.create_sequence(
        project.id,
        "Greeting",
        [{"robot_pose_id": pose.id, "hold_ms": 700, "transition_ms": 300}],
    )

    response = client.put(
        f"/studio/sequences/{sequence.id}",
        json={
            "name": "Broken",
            "steps": [
                {"robot_pose_id": "missing-pose", "hold_ms": 900, "transition_ms": 450}
            ],
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Referenced resource not found"}
    saved = repo.get_sequence(sequence.id)
    assert saved.name == "Greeting"
    assert saved.steps[0].robot_pose_id == pose.id


def test_sequence_update_rejects_whitespace_only_name(
    client: TestClient, repo: StudioRepository
) -> None:
    project = repo.create_project("Classroom")
    pose = repo.create_robot_pose(project.id, "Wave", {"l_sho_pitch": 0.4})
    sequence = repo.create_sequence(
        project.id,
        "Greeting",
        [{"robot_pose_id": pose.id, "hold_ms": 700, "transition_ms": 300}],
    )

    response = client.put(
        f"/studio/sequences/{sequence.id}",
        json={
            "name": "   ",
            "steps": [{"robot_pose_id": pose.id, "hold_ms": 900, "transition_ms": 450}],
        },
    )

    assert response.status_code == 422
    assert repo.get_sequence(sequence.id).name == "Greeting"


def test_interaction_order_and_delete_endpoints_persist_changes(
    client: TestClient, repo: StudioRepository
) -> None:
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

    reordered = client.put(
        "/studio/interactions/order",
        json={"project_id": project.id, "rule_ids": [rules[1].id, rules[0].id]},
    )
    deleted = client.delete(f"/studio/interactions/{rules[1].id}")

    assert reordered.status_code == 200
    assert reordered.json() == {"reordered": True}
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True}
    assert [rule.id for rule in repo.list_behavior_rules(project.id)] == [rules[0].id]


def test_import_with_dangling_reference_returns_422(
    client: TestClient, repo: StudioRepository
) -> None:
    project = repo.create_project("Classroom")
    before = client.get(f"/studio/projects/{project.id}/export").json()
    broken = {
        **before,
        "rules": [
            {
                "id": "rule-1",
                "project_id": project.id,
                "human_pose_id": "missing",
                "sequence_id": "missing",
                "cooldown_seconds": 2.0,
                "priority": 0,
                "enabled": True,
            }
        ],
    }

    response = client.post("/studio/projects/import", json=broken)

    assert response.status_code == 422
    assert client.get(f"/studio/projects/{project.id}/export").json() == before


def test_oversized_import_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/studio/projects/import",
        content=b"x" * (5 * 1024 * 1024 + 1),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413


def test_robot_pose_preview_uses_the_simulator(repo: StudioRepository) -> None:
    project = repo.create_project("Classroom")
    pose = repo.create_robot_pose(
        project.id,
        "Reach high",
        {"l_sho_pitch": 0.4},
        safety={"safe": True},
    )

    class PreviewRuntime:
        def __init__(self) -> None:
            self.pose_id: str | None = None

        async def preview_pose(self, pose_id: str) -> PlaybackResult:
            self.pose_id = pose_id
            return PlaybackResult("completed", 1)

    runtime = PreviewRuntime()
    configure_studio(repo, runtime)  # type: ignore[arg-type]
    app = FastAPI()
    app.include_router(router)

    with TestClient(app) as test_client:
        response = test_client.post(f"/studio/robot-poses/{pose.id}/preview")

    assert response.status_code == 200
    assert response.json() == {
        "status": "completed",
        "completed_steps": 1,
        "failed_step": None,
        "reason": None,
    }
    assert runtime.pose_id == pose.id


def test_missing_robot_pose_preview_returns_404(repo: StudioRepository) -> None:
    class MissingPoseRuntime:
        async def preview_pose(self, pose_id: str) -> PlaybackResult:
            raise KeyError(pose_id)

    configure_studio(repo, MissingPoseRuntime())  # type: ignore[arg-type]
    app = FastAPI()
    app.include_router(router)

    with TestClient(app) as test_client:
        response = test_client.post('/studio/robot-poses/missing/preview')

    assert response.status_code == 404
    assert response.json() == {'detail': 'Robot pose not found'}
