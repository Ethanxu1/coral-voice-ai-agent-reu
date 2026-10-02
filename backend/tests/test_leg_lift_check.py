"""Hardware leg-lift check: the pure planning parts (no robot, no server).

The script drives the real robot through the main server's /move, so what
is testable here is WHAT it sends: only leg joints, the exact controller
shift, a lift that runs the real LegLiftController and ends at stand, and
the abort rule.
"""

from __future__ import annotations

import pytest

from app.robot.angle_utils import rad_to_servo_units
from app.robot.leg_lift_check import (
    ABORT_ROLL_DEG,
    CHECK_JOINTS,
    HARD_ABORT_DEG,
    LeanGuard,
    foot_fraction,
    lean_breakdown,
    lift_poses,
    shift_fraction,
    shift_pose,
    should_abort,
    single_joint_pose,
    stand_pose,
    to_moves,
    with_stance_comp,
)
from app.robot.servo_config import SERVO_ID_MAP
from app.vision.leg_lift_controller import ANKLE_SHIFT, HIP_RATIO, _stand

LEG = {"l_hip_pitch", "r_hip_pitch", "l_hip_roll", "r_hip_roll",
       "l_knee", "r_knee", "l_ank_roll", "r_ank_roll"}


def test_only_leg_and_ankle_roll_joints_are_ever_touched():
    assert set(CHECK_JOINTS) == LEG
    assert set(stand_pose()) == LEG


def test_moves_use_servo_ids_and_sim_units():
    moves = to_moves({"l_ank_roll": 0.1}, 400)
    assert moves == [{"servo_id": SERVO_ID_MAP["l_ank_roll"],
                      "position": rad_to_servo_units(0.1), "duration_ms": 400}]


def test_single_joint_pose_moves_only_that_joint():
    pose = single_joint_pose("r_ank_roll", -0.12)
    for j, v in pose.items():
        expected = _stand(j) - 0.12 if j == "r_ank_roll" else _stand(j)
        assert v == pytest.approx(expected), j


@pytest.mark.parametrize("swing,sign", [("l", -1.0), ("r", 1.0)])
def test_shift_pose_is_the_controllers_parallelogram(swing, sign):
    pose = shift_pose(swing)
    for a in ("l_ank_roll", "r_ank_roll"):
        assert pose[a] - _stand(a) == pytest.approx(sign * ANKLE_SHIFT)
    for h in ("l_hip_roll", "r_hip_roll"):
        assert pose[h] - _stand(h) == pytest.approx(sign * HIP_RATIO * ANKLE_SHIFT)
    for j in ("l_hip_pitch", "r_hip_pitch", "l_knee", "r_knee"):
        assert pose[j] == pytest.approx(_stand(j))


@pytest.mark.parametrize("swing", ["l", "r"])
def test_lift_runs_the_real_controller_and_ends_at_stand(swing):
    poses = list(lift_poses(swing, height=0.3))
    hip = f"{swing}_hip_pitch"
    peak = max(abs(p[hip] - _stand(hip)) for p in poses)
    assert peak > 0.15, "the leg never lifted"
    # while the foot is up, the weight is fully across
    up = [p for p in poses if abs(p[hip] - _stand(hip)) > 0.9 * peak]
    for p in up:
        assert abs(p["l_ank_roll"] - _stand("l_ank_roll")) == pytest.approx(ANKLE_SHIFT, abs=1e-3)
    for j, v in poses[-1].items():
        assert v == pytest.approx(_stand(j), abs=1e-6), j
    assert all(set(p) == LEG for p in poses)


@pytest.mark.parametrize("swing", ["l", "r"])
def test_shift_and_foot_fractions_read_back_from_poses(swing):
    assert shift_fraction(stand_pose(), swing) == pytest.approx(0.0)
    assert shift_fraction(shift_pose(swing), swing) == pytest.approx(1.0)
    poses = list(lift_poses(swing, height=0.3))
    assert max(foot_fraction(p, swing) for p in poses) == pytest.approx(0.3, abs=0.02)


def test_lean_breakdown_separates_the_slide_from_the_foot_lift():
    rows = [(0.0, 0.0, 0.0, 0.0), (0.1, 1.0, 0.5, 0.0), (0.2, 2.0, 1.0, 0.0),
            (0.3, 3.0, 1.0, 0.05), (0.4, -8.5, 1.0, 0.2), (0.5, None, 1.0, 0.2)]
    b = lean_breakdown(rows)
    assert b["after_shift"] == 2.0
    assert b["foot_leaves"] == 3.0
    assert b["worst"] == -8.5 and b["worst_foot"] == 0.2
    assert b["worst_foot_up"] == -8.5


def test_abort_on_a_lean_beyond_the_limit_either_way():
    assert not should_abort(2.0 + ABORT_ROLL_DEG - 0.1, 2.0)
    assert should_abort(2.0 + ABORT_ROLL_DEG + 0.1, 2.0)
    assert should_abort(2.0 - ABORT_ROLL_DEG - 0.1, 2.0)
    assert should_abort(None, 2.0), "no IMU reading mid-lift must stop the test"


def test_one_jolt_past_the_limit_does_not_stop_the_lift():
    """The 2026-10-02 left lift: clean, but one reading hit -9.2 deg."""
    g = LeanGuard(-2.5)
    for roll in (-2.3, -7.5, -2.0, -11.7, -3.0):
        assert not g.update(roll)


def test_a_lean_that_persists_stops_the_lift():
    g = LeanGuard(0.0)
    assert not g.update(9.0)
    assert g.update(9.5)


def test_a_large_lean_stops_the_lift_at_once():
    assert LeanGuard(0.0).update(-(HARD_ABORT_DEG + 0.1))


def test_lost_imu_readings_stop_the_lift():
    g = LeanGuard(0.0)
    assert not g.update(None)
    assert g.update(None)


@pytest.mark.parametrize("swing,stance,sign", [("l", "r", 1.0), ("r", "l", -1.0)])
def test_stance_comp_eases_the_standing_hip_back_only_while_the_foot_is_up(swing, stance, sign):
    poses = list(lift_poses(swing, height=0.3))
    hip = f"{stance}_hip_roll"
    up = max(poses, key=lambda p: foot_fraction(p, swing))
    assert with_stance_comp(up, swing, 0.1)[hip] - up[hip] == pytest.approx(sign * 0.1)
    # standing hip only; swing hip and ankles untouched
    changed = {j for j in up if with_stance_comp(up, swing, 0.1)[j] != up[j]}
    assert changed == {hip}
    # nothing while both feet are down (during the slide, after landing)
    assert with_stance_comp(shift_pose(swing), swing, 0.1) == shift_pose(swing)
    assert with_stance_comp(poses[-1], swing, 0.1) == poses[-1]
