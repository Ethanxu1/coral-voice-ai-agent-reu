"""Tests for POST /set-pose (Pose Tester and Rock Paper Scissors)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.routes import motion as motion_routes
from app.main import create_app
from app.robot.angle_utils import rad_to_servo_units
from app.robot.hardware_angle_utils import hardware_units_to_rad
from app.robot.servo_config import SERVO_ID_MAP
from app.state import state

pytestmark = pytest.mark.db


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        state.simulator.reset_pose()
        yield c


def _fall_gate(sim, targets, context, check_fall=True):
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


def test_wait_until_arrived_returns_once_the_body_is_there(client):
    """The Dance Game starts its next move when /set-pose returns. The position
    motors trail the glide (the soft arms by ~0.25 rad here), so with
    wait_until_arrived the joint must physically be at the pose by then, not
    just its motor target."""
    target = hardware_units_to_rad(513, "l_sho_roll")  # arm out to the side

    data = client.post(
        "/set-pose",
        json={
            "pulses": {"l_sho_roll": 513},
            "duration_ms": 700,
            "skip_collision_check": True,
            "wait_until_arrived": True,
        },
    ).json()

    assert data["status"] == "done"
    actual = state.simulator.get_actual_joint_positions(["l_sho_roll"])["l_sho_roll"]
    assert actual == pytest.approx(target, abs=0.06)


def test_glide_routes_around_a_collision_on_the_way(client, monkeypatch):
    """Wave -> Dab (Dance Game) collides part-way on the straight path. The
    glide must go around through intermediate poses and still end at Dab,
    instead of stopping at the last safe point."""
    wave = {"r_sho_pitch": 0, "r_sho_roll": 500, "r_el_pitch": 500, "r_el_yaw": 940}
    dab = {"r_sho_pitch": 675, "r_sho_roll": 225, "r_el_pitch": 120, "r_el_yaw": 890}
    for joint, pulse in wave.items():
        state.simulator.set_joint_position(joint, hardware_units_to_rad(pulse, joint))
    legs = []

    async def record(commands, sim_only=None):
        legs.append({c.servo_id: c.position for c in commands})

    monkeypatch.setattr(motion_routes, "dispatch_servo_commands", record)

    data = client.post(
        "/set-pose", json={"pulses": dab, "duration_ms": 1000, "check_fall": False}
    ).json()

    assert data["safety"]["collision_clamped"] is False
    assert len(legs) >= 2, "expected the glide to go through an intermediate pose"
    for joint, pulse in dab.items():
        expected = rad_to_servo_units(hardware_units_to_rad(pulse, joint))
        assert legs[-1][SERVO_ID_MAP[joint]] == pytest.approx(expected, abs=1)


def test_to_robot_follows_the_robot_mode(client, monkeypatch):
    """Rock Paper Scissors asks for its moves to reach the robot: the dispatch
    then follows the server's sim/robot mode (sim_only=None) instead of being
    pinned to the sim."""
    calls = []

    async def record(commands, sim_only=None):
        calls.append(sim_only)

    monkeypatch.setattr(motion_routes, "dispatch_servo_commands", record)

    client.post(
        "/set-pose",
        json={"pulses": {"l_sho_pitch": 500}, "duration_ms": 800, "to_robot": True},
    )

    assert calls == [None]


@pytest.mark.parametrize(
    "unsafe",
    [{"skip_collision_check": True}, {"duration_ms": 0}],
    ids=["unchecked", "instant"],
)
def test_to_robot_refuses_unchecked_or_instant_poses(client, unsafe):
    """A pose for the robot must go through the safety gate and be a timed
    glide: an unchecked or instant pose stays a Pose Tester (sim) thing."""
    body = {"pulses": {"l_sho_pitch": 500}, "duration_ms": 800, "to_robot": True, **unsafe}

    assert client.post("/set-pose", json=body).status_code == 422


def test_unknown_joint_is_skipped(client):
    data = client.post("/set-pose", json={"pulses": {"tail": 500}}).json()
    assert data["skipped"] == ["tail"]


class _AlwaysFalls:
    def check_fall(self, target_joints, current_joints=None):
        return {"fell": True, "head_z": 0.05, "stand_head_z": 0.36, "threshold_z": 0.25}


def test_pose_tester_can_skip_the_fall_check(client, monkeypatch):
    """check_fall=false (Pose Tester) skips only the fall check; the default
    (Rock Paper Scissors) still blocks a toppling pose."""
    monkeypatch.setattr(state, "stability_checker", _AlwaysFalls())
    pose = {"l_sho_pitch": 500}

    assert client.post("/set-pose", json={"pulses": pose}).json()["status"] == "blocked"
    data = client.post("/set-pose", json={"pulses": pose, "check_fall": False}).json()
    assert data["status"] == "done"
    assert data["safety"]["fall_blocked"] is False


def test_upright_pin_endpoint_toggles_the_sim(client):
    client.post("/sim/upright", json={"enabled": True})
    assert state.simulator.upright_pinned is True
    client.post("/sim/upright", json={"enabled": False})
    assert state.simulator.upright_pinned is False
