"""Tests for pinning the simulated robot upright (used by the test pages)."""

from __future__ import annotations

import numpy as np
import pytest

from app.robot.hardware_angle_utils import hardware_units_to_rad
from app.simulator import AiNexSimulator

# A crouch extreme enough to topple the free-standing robot.
_TOPPLING_PULSES = {
    **{j: 150 for j in ("l_hip_yaw", "l_hip_roll", "l_hip_pitch", "l_knee", "l_ank_pitch", "l_ank_roll")},
    **{j: 850 for j in ("r_hip_yaw", "r_hip_roll", "r_hip_pitch", "r_knee", "r_ank_pitch", "r_ank_roll")},
}


def _settle_in_toppling_pose(sim: AiNexSimulator, seconds: float = 3.0) -> np.ndarray:
    for joint, pulse in _TOPPLING_PULSES.items():
        sim.set_joint_position(joint, hardware_units_to_rad(pulse, joint))
    for _ in range(int(seconds / 0.01)):
        sim.step()
    return sim.base_pose()


def test_unpinned_robot_topples_in_this_pose():
    """Sanity check: the pose really does knock the free robot over."""
    sim = AiNexSimulator()
    upright = sim.base_pose()
    fallen = _settle_in_toppling_pose(sim)
    assert fallen[2] < upright[2] * 0.7


def test_pinned_robot_stays_upright():
    sim = AiNexSimulator()
    upright = sim.base_pose()
    sim.set_upright_pinned(True)
    pinned = _settle_in_toppling_pose(sim)
    np.testing.assert_allclose(pinned, upright, atol=1e-6)


def test_pinning_a_fallen_robot_stands_it_up():
    sim = AiNexSimulator()
    upright = sim.base_pose()
    _settle_in_toppling_pose(sim)
    sim.set_upright_pinned(True)
    np.testing.assert_allclose(sim.base_pose(), upright, atol=1e-6)


def test_unpinning_releases_the_base():
    sim = AiNexSimulator()
    sim.set_upright_pinned(True)
    sim.set_upright_pinned(False)
    assert sim.upright_pinned is False


def _yaw_deg(quat_wxyz: np.ndarray) -> float:
    w, x, y, z = quat_wxyz
    return float(np.degrees(np.arctan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))))


@pytest.mark.parametrize("arms", [
    {},  # plain stand
    {"r_sho_pitch": 700, "l_sho_roll": 600, "l_el_yaw": 150},  # one arm up, one out (a Pose Designer pose)
])
def test_standing_robot_does_not_spin_or_slide(arms):
    """Left alone, the robot stays where it stands. Without torsional floor
    friction (condim 4) and noslip it spun ~0.5 deg/s and crept ~0.5 mm/s on
    servo jitter, which threw the Pose Designer ghost off the live robot."""
    sim = AiNexSimulator()
    for joint, pulse in arms.items():
        sim.set_joint_position(joint, hardware_units_to_rad(pulse, joint))
    for _ in range(200):  # 2 s to settle into the pose
        sim.step()
    start = sim.base_pose()
    for _ in range(3000):  # 30 s
        sim.step()
    end = sim.base_pose()
    assert abs(_yaw_deg(end[3:]) - _yaw_deg(start[3:])) < 1.0
    assert np.hypot(*(end[:2] - start[:2])) < 0.005
