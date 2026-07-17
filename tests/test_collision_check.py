"""Tests for the shadow-rollout collision checker."""

import math

import pytest

from coral_agent.collision.collision_checker import CollisionChecker
from coral_agent.simulator import AiNexSimulator


@pytest.fixture(scope="module")
def checker() -> CollisionChecker:
    return CollisionChecker()


@pytest.fixture(scope="module")
def stand_joints() -> dict[str, float]:
    # Use the same stand keyframe the live simulator uses so tests match runtime.
    sim = AiNexSimulator()
    return sim.get_all_joint_states()


def test_safe_trajectory_passes_untouched(checker, stand_joints):
    target = dict(stand_joints)
    target["head_pan"] = stand_joints.get("head_pan", 0.0) + 0.5

    safe, frac, bad = checker.check_trajectory(stand_joints, target)

    assert frac == 1.0, f"expected full-motion safe, got {frac} with {bad}"
    assert bad == []
    assert math.isclose(safe["head_pan"], target["head_pan"], abs_tol=1e-9)


def test_no_op_target_is_safe(checker, stand_joints):
    safe, frac, bad = checker.check_trajectory(stand_joints, dict(stand_joints))
    assert frac == 1.0
    assert bad == []


def test_colliding_trajectory_is_reduced(checker, stand_joints):
    # Drive the right arm hard inward and forward — geometry forces the forearm
    # or gripper through the torso before the target angle is reached.
    target = dict(stand_joints)
    target["r_sho_roll"] = 0.0        # from stand's outward pose, swing inward
    target["r_sho_pitch"] = 1.6       # up and forward
    target["r_el_yaw"] = -2.0         # elbow fully bent
    target["r_el_pitch"] = -1.5

    safe, frac, bad = checker.check_trajectory(stand_joints, target)

    assert frac < 1.0, "expected the checker to flag a collision"
    assert bad, "expected at least one bad contact pair to be reported"

    # Every backed-off joint should be strictly closer to its start than the target.
    for joint in ("r_sho_roll", "r_sho_pitch", "r_el_yaw", "r_el_pitch"):
        start = stand_joints[joint]
        end = target[joint]
        capped = safe[joint]
        travelled = abs(capped - start)
        full = abs(end - start)
        assert travelled < full, (
            f"{joint} should have moved less than the full target "
            f"({travelled:.3f} vs {full:.3f})"
        )


def test_buffer_steps_stop_motion_earlier(stand_joints):
    # Same collision pose, checked with and without a buffer. The buffered
    # version must back off strictly further (smaller safe_fraction).
    target = dict(stand_joints)
    target["r_sho_roll"] = 0.0
    target["r_sho_pitch"] = 1.6
    target["r_el_yaw"] = -2.0
    target["r_el_pitch"] = -1.5

    no_buffer = CollisionChecker(buffer_steps=0)
    buffered = CollisionChecker(buffer_steps=3)

    _, frac_none, _ = no_buffer.check_trajectory(stand_joints, target)
    _, frac_buf, _ = buffered.check_trajectory(stand_joints, target)

    assert frac_none < 1.0 and frac_buf < 1.0, "expected both to flag"
    assert frac_buf < frac_none, (
        f"buffer should stop earlier: buffered={frac_buf} vs none={frac_none}"
    )


def test_all_moving_joints_share_the_same_safe_fraction(checker, stand_joints):
    # Fluid-motion invariant: on a reduced trajectory every moving joint should
    # be capped at the same fraction, so they still finish together.
    target = dict(stand_joints)
    target["r_sho_roll"] = 0.0
    target["r_sho_pitch"] = 1.6
    target["r_el_yaw"] = -2.0

    safe, frac, bad = checker.check_trajectory(stand_joints, target)
    if frac == 1.0:
        pytest.skip("this pose did not trigger a collision; nothing to verify")

    fractions = []
    for joint in ("r_sho_roll", "r_sho_pitch", "r_el_yaw"):
        start = stand_joints[joint]
        end = target[joint]
        if abs(end - start) < 1e-9:
            continue
        fractions.append((safe[joint] - start) / (end - start))

    assert fractions, "expected at least one moving joint to compare"
    for f in fractions[1:]:
        assert math.isclose(f, fractions[0], abs_tol=1e-6), (
            f"per-joint fractions diverged: {fractions}"
        )
