"""Tests for re-checking an already-applied raw joint move against the same
self-collision/fall safety gate as /move (`collision_checked_targets`'s
explicit `current` override and `apply_safety_clamp_to_sim`).

Motivating bug: the /test page's raw joint-jog buttons applied moves directly
to the simulator with no safety check at all -- `collision_checked_targets()`
always read "current" from the sim's live state, which only works when the
sim hasn't moved yet. For a command already applied instantly to the sim,
that meant current == target (no apparent movement), so a real collision was
never detected.
"""

import pytest

from app.collision.collision_checker import CollisionChecker
from app.services.motion import apply_safety_clamp_to_sim, collision_checked_targets
from app.simulator import AiNexSimulator
from app.state import state


class _RecordingSim:
    """Minimal stand-in for AiNexSimulator: tracks joints in a plain dict."""

    def __init__(self, joints: dict[str, float]) -> None:
        self._joints = dict(joints)

    def get_all_joint_states(self) -> dict[str, float]:
        return dict(self._joints)

    def set_joint_position(self, joint_name: str, position: float) -> None:
        self._joints[joint_name] = position


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


def test_collision_checked_targets_uses_explicit_current_not_sim_state(checkers, stand_joints):
    target = _colliding_target(stand_joints)

    # The sim has already been moved to `target` (as a raw debug command
    # would do, instantly, before any safety check runs). If the function
    # ignored the explicit `current` and read the sim's live state instead,
    # it would see current == target -- no apparent movement -- and never
    # flag the collision.
    sim_already_at_target = _RecordingSim(target)

    _safe, report = collision_checked_targets(
        sim_already_at_target, target, "test", current=stand_joints
    )

    assert report["collision_clamped"], (
        "expected the explicit `current` (stand) to be used for the check, "
        "not the sim's already-moved live state"
    )


def test_apply_safety_clamp_to_sim_rolls_back_a_raw_colliding_move(checkers, stand_joints):
    before = dict(stand_joints)
    after = _colliding_target(stand_joints)

    sim = _RecordingSim(after)  # sim already applied the naive, unchecked move
    report = apply_safety_clamp_to_sim(sim, before, after, "test raw command")

    assert report["collision_clamped"]
    assert report["bad_pairs"]

    final = sim.get_all_joint_states()
    full_delta = abs(after["r_sho_pitch"] - before["r_sho_pitch"])
    clamped_delta = abs(final["r_sho_pitch"] - before["r_sho_pitch"])
    assert clamped_delta < full_delta, (
        "expected the sim to be rolled back toward `before`, not left at the "
        "full colliding target"
    )


def test_apply_safety_clamp_to_sim_is_a_no_op_when_safe(checkers, stand_joints):
    before = dict(stand_joints)
    after = dict(stand_joints)
    after["head_pan"] = stand_joints.get("head_pan", 0.0) + 0.3

    sim = _RecordingSim(after)
    report = apply_safety_clamp_to_sim(sim, before, after, "test safe command")

    assert not report["collision_clamped"]
    assert not report["fall_blocked"]
    assert sim.get_all_joint_states()["head_pan"] == after["head_pan"]
