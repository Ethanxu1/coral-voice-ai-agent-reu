"""HTTP contracts for Motion Block Studio."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.studio import configure_studio, router
from app.studio.repository import StudioRepository
from app.studio.runtime import StudioRuntime


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
