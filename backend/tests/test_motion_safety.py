"""Tests for collision_checked_targets, the safety gate every dispatch path
(including the /test page jog buttons) runs before moving the robot."""

import pytest

from app.collision.collision_checker import CollisionChecker
from app.services.motion import collision_checked_targets
from app.simulator import AiNexSimulator
from app.state import state


class _RecordingSim:
    """Minimal stand-in for AiNexSimulator: tracks joints in a plain dict."""

    def __init__(self, joints: dict[str, float]) -> None:
        self._joints = dict(joints)

    def get_all_joint_states(self) -> dict[str, float]:
        return dict(self._joints)


@pytest.fixture
def checkers():
    old_collision = state.collision_checker
    old_stability = state.stability_checker
    state.collision_checker = CollisionChecker()
    state.stability_checker = None  # isolate from the fall check in these tests
    yield
    state.collision_checker = old_collision
    state.stability_checker = old_stability


@pytest.fixture(scope="module")
def stand_joints() -> dict[str, float]:
    sim = AiNexSimulator()
    return sim.get_all_joint_states()


def _colliding_target(stand_joints: dict[str, float]) -> dict[str, float]:
    # Same pose as test_collision_check.py's colliding-trajectory case: right
    # arm swung inward/forward with the elbow bent, forcing it through the torso.
    target = dict(stand_joints)
    target["r_sho_roll"] = 0.0
    target["r_sho_pitch"] = 1.6
    target["r_el_yaw"] = -2.0
    target["r_el_pitch"] = -1.5
    return target


def test_colliding_target_is_clamped_short_of_contact(checkers, stand_joints):
    target = _colliding_target(stand_joints)
    safe, report = collision_checked_targets(_RecordingSim(stand_joints), target, "test")

    assert report["collision_clamped"]
    assert report["bad_pairs"]
    full_delta = abs(target["r_sho_pitch"] - stand_joints["r_sho_pitch"])
    safe_delta = abs(safe["r_sho_pitch"] - stand_joints["r_sho_pitch"])
    assert safe_delta < full_delta


def test_safe_target_passes_unchanged(checkers, stand_joints):
    target = dict(stand_joints)
    target["head_pan"] = stand_joints.get("head_pan", 0.0) + 0.3
    safe, report = collision_checked_targets(_RecordingSim(stand_joints), target, "test")

    assert not report["collision_clamped"]
    assert not report["fall_blocked"]
    assert safe["head_pan"] == pytest.approx(target["head_pan"])
