"""Tests for the /test page button targets (simulator.command_targets)."""

from __future__ import annotations

import pytest

from app.simulator import AiNexSimulator
from app.simulator.mujoco_sim import JOG_COMMANDS, PRESET_POSES, command_targets


@pytest.fixture(scope="module")
def sim():
    return AiNexSimulator()


@pytest.mark.parametrize("command, joint, direction", [
    ("head_left", "head_pan", -1),
    ("left_arm_up", "l_sho_pitch", +1),
    ("right_arm_out", "r_sho_roll", -1),
    ("right_knee_bend", "r_knee", -1),
])
def test_jog_targets_one_step_in_direction_without_moving(sim, command, joint, direction):
    sim.set_joint_position(joint, 0.0)
    assert command_targets(sim, command) == {joint: pytest.approx(direction * sim.STEP_SIZE)}
    assert sim.get_joint_position(joint) == 0.0


def test_jog_target_is_clamped_to_joint_limits(sim):
    from app.validation import JOINT_LIMITS

    sim.set_joint_position("head_pan", JOINT_LIMITS["head_pan"].max)
    assert command_targets(sim, "head_right") == {"head_pan": JOINT_LIMITS["head_pan"].max}


def test_preset_targets(sim):
    assert command_targets(sim, "wave") == PRESET_POSES["wave"]


def test_every_jog_command_names_a_real_joint(sim):
    for joint, _ in JOG_COMMANDS.values():
        sim.get_joint_position(joint)  # raises ValueError on an unknown joint


def test_unknown_command_is_rejected(sim):
    assert command_targets(sim, "do_a_backflip") is None
