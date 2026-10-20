"""Tests for POST /set-pose, the Pose Tester's sim endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.routes import motion as motion_routes
from app.main import create_app
from app.state import state

pytestmark = pytest.mark.db


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        state.simulator.reset_pose()
        yield c


def _fall_gate(sim, targets, context):
    current = sim.get_all_joint_states()
    return dict(current), {
        "fall_blocked": True,
        "collision_clamped": False,
        "safe_fraction": 0.0,
        "bad_pairs": [],
    }


def test_blocked_pose_is_reported_not_claimed_as_applied(client, monkeypatch):
    """A pose the fall check blocks must say so — it used to come back as
    'done, applied N joints' while nothing moved."""
    monkeypatch.setattr(motion_routes, "collision_checked_targets", _fall_gate)

    data = client.post("/set-pose", json={"pulses": {"l_sho_pitch": 500}}).json()

    assert data["status"] == "blocked"
    assert data["safety"]["fall_blocked"] is True


def test_safe_pose_reports_safety_verdict(client):
    data = client.post("/set-pose", json={"pulses": {"l_sho_pitch": 500}}).json()

    assert data["status"] == "done"
    assert data["applied"] == ["l_sho_pitch"]
    assert data["safety"]["fall_blocked"] is False


def test_duration_glides_through_the_dispatcher(client, monkeypatch):
    """With a move time the sim glides there (sim only), instead of snapping."""
    calls = []

    async def record(commands, sim_only=None):
        calls.append((commands, sim_only))

    monkeypatch.setattr(motion_routes, "dispatch_servo_commands", record)
    start = state.simulator.get_joint_position("l_sho_pitch")

    client.post("/set-pose", json={"pulses": {"l_sho_pitch": 500}, "duration_ms": 800})

    assert state.simulator.get_joint_position("l_sho_pitch") == pytest.approx(start)
    [(commands, sim_only)] = calls
    assert sim_only is True
    assert [c.duration_ms for c in commands] == [800]


def test_unknown_joint_is_skipped(client):
    data = client.post("/set-pose", json={"pulses": {"tail": 500}}).json()
    assert data["skipped"] == ["tail"]
