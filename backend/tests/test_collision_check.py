"""Tests for the shadow-rollout collision checker."""

import math

import pytest

from app.collision.collision_checker import CollisionChecker
from app.robot.hardware_angle_utils import hardware_units_to_rad
from app.simulator import AiNexSimulator


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


def test_buffer_fraction_stops_motion_earlier(stand_joints):
    # Same collision pose, checked with and without a buffer. The buffered
    # version must back off strictly further (smaller safe_fraction).
    target = dict(stand_joints)
    target["r_sho_roll"] = 0.0
    target["r_sho_pitch"] = 1.6
    target["r_el_yaw"] = -2.0
    target["r_el_pitch"] = -1.5

    no_buffer = CollisionChecker(buffer_fraction=0.0)
    buffered = CollisionChecker(buffer_fraction=0.05)

    _, frac_none, _ = no_buffer.check_trajectory(stand_joints, target)
    _, frac_buf, _ = buffered.check_trajectory(stand_joints, target)

    assert frac_none < 1.0 and frac_buf < 1.0, "expected both to flag"
    assert frac_buf < frac_none, (
        f"buffer should stop earlier: buffered={frac_buf} vs none={frac_none}"
    )


def test_default_buffer_stays_close_to_true_contact_boundary(stand_joints):
    # The default buffer must be a small, near-exact margin before the real
    # contact point -- not inflated by the coarse scan's step discretization.
    # A high-resolution, zero-buffer reference checker gives the true contact
    # fraction; the default checker's safe_fraction must land within a small
    # tolerance of it (tolerance = default buffer_fraction + a little slack
    # for bisection precision).
    target = dict(stand_joints)
    target["r_sho_roll"] = 0.0
    target["r_sho_pitch"] = 1.6
    target["r_el_yaw"] = -2.0
    target["r_el_pitch"] = -1.5

    reference = CollisionChecker(num_steps=1000, buffer_fraction=0.0)
    _, true_frac, _ = reference.check_trajectory(stand_joints, target)

    default_checker = CollisionChecker()
    _, safe_frac, _ = default_checker.check_trajectory(stand_joints, target)

    assert true_frac < 1.0, "expected the reference checker to find the collision too"
    gap = true_frac - safe_frac
    assert 0.0 <= gap <= 0.03, (
        f"default buffer should hold back <=3% of the trajectory past the "
        f"true contact point ({true_frac:.4f}); got safe_fraction={safe_frac:.4f} "
        f"(gap={gap:.2%})"
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


def _rad(pulses: dict[str, int]) -> dict[str, float]:
    return {j: hardware_units_to_rad(p, j) for j, p in pulses.items()}


# The Dance Game's Wave and Dab right arms. Both poses are collision-free, but
# the straight move between them folds the elbow while twisting the upper arm,
# which swings the forearm into the upper arm part-way.
WAVE_R_ARM = _rad({"r_sho_pitch": 0, "r_sho_roll": 500, "r_el_pitch": 500, "r_el_yaw": 940})
DAB_R_ARM = _rad({"r_sho_pitch": 675, "r_sho_roll": 225, "r_el_pitch": 120, "r_el_yaw": 890})


def test_plan_routes_around_a_collision_on_the_way(checker, stand_joints):
    start = {**stand_joints, **WAVE_R_ARM}
    assert checker.check_trajectory(start, DAB_R_ARM)[1] < 1.0, "precondition: straight path collides"

    path = checker.plan_path(start, DAB_R_ARM)

    assert path is not None and len(path) >= 2, "expected a detour through at least one pose"
    for joint, target in DAB_R_ARM.items():
        assert path[-1][joint] == pytest.approx(target)
    for a, b in zip([start, *path], path):
        assert checker.check_trajectory(a, b)[1] == 1.0, "every leg of the detour must be clear"


def test_plan_is_the_straight_move_when_nothing_is_in_the_way(checker, stand_joints):
    target = {"head_pan": stand_joints["head_pan"] + 0.5}

    path = checker.plan_path(stand_joints, target)

    assert path == [{**stand_joints, **target}]


def test_plan_gives_up_when_the_target_itself_collides(checker, stand_joints):
    """No route reaches a pose whose limbs overlap the body; the caller then
    falls back to stopping at the last safe point."""
    target = {"r_sho_roll": 0.0, "r_sho_pitch": 1.6, "r_el_yaw": -2.0, "r_el_pitch": -1.5}
    checker.render_pose({**stand_joints, **target})
    assert checker._contact_pairs(), "precondition: the target pose is in contact"

    assert checker.plan_path(stand_joints, target) is None
