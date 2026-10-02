"""Leg-roll servo directions, pinned to what the physical robot did.

The leg lift's weight shift rolls both ankles and both hips together. In
the sim, a NEGATIVE delta on every one of them moves the weight onto the
robot's right foot (measured in sim: each foot then lifts the edge on the
robot's right side, and each foot swings toward the robot's left when the
robot is held in the air). The real servos must turn the same way.

Observed on the robot, 2026-10-02 (held in the air, one servo at a time):
  servo 1 (l_ank_roll): sim -0.12 rad lifts the left foot's INNER edge   -- matches sim
  servo 2 (r_ank_roll): pulse 560 lifts the right foot's INNER edge, i.e.
                        the sim's -0.12 (outer edge up) needs pulse < 500
  servo 9 (l_hip_roll): sim -0.18 swings the left leg OUTWARD           -- matches sim
  servo 10 (r_hip_roll): sim +0.18 swings the right leg OUTWARD         -- matches sim
"""

from __future__ import annotations

from app.robot.hardware_angle_utils import HW_STAND_RAD, rad_to_hardware_units
from app.robot.servo_config import STAND_PULSE


def _pulse_for(joint: str, delta: float) -> int:
    return rad_to_hardware_units(HW_STAND_RAD.get(joint, 0.0) + delta, joint)


def test_right_ankle_tilts_the_way_the_sim_does():
    """Was -1: the sim's weight-shift tilt came out mirrored on the robot."""
    assert _pulse_for("r_ank_roll", -0.12) < STAND_PULSE["r_ank_roll"]


def test_left_ankle_tilts_the_way_the_sim_does():
    assert _pulse_for("l_ank_roll", -0.12) < STAND_PULSE["l_ank_roll"]


def test_hips_swing_the_way_the_sim_does():
    # servo 9: lower pulse = outward (user sweep); servo 10: higher = outward
    assert _pulse_for("l_hip_roll", -0.18) < STAND_PULSE["l_hip_roll"]
    assert _pulse_for("r_hip_roll", +0.18) > STAND_PULSE["r_hip_roll"]
