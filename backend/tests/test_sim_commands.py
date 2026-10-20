"""Tests for the /test page button commands (simulator.execute_command)."""

from __future__ import annotations

import pytest

from app.simulator import AiNexSimulator
from app.simulator.mujoco_sim import JOG_COMMANDS, PRESET_POSES, execute_command


@pytest.fixture(scope="module")
def sim():
    return AiNexSimulator()


@pytest.mark.parametrize("command, joint, direction", [
    ("head_left", "head_pan", -1),
    ("left_arm_up", "l_sho_pitch", +1),
    ("right_arm_out", "r_sho_roll", -1),
    ("right_knee_bend", "r_knee", -1),
])
def test_jog_moves_joint_one_step_in_direction(sim, command, joint, direction):
    sim.set_joint_position(joint, 0.0)
    assert execute_command(sim, command)
    assert sim.get_joint_position(joint) == pytest.approx(direction * sim.STEP_SIZE)


def test_preset_pose_sets_targets(sim):
    assert execute_command(sim, "wave")
    for joint, target in PRESET_POSES["wave"].items():
        assert sim.get_joint_position(joint) == pytest.approx(target)


def test_every_jog_command_names_a_real_joint(sim):
    for joint, _ in JOG_COMMANDS.values():
        sim.get_joint_position(joint)  # raises ValueError on an unknown joint


def test_unknown_command_is_rejected(sim):
    assert execute_command(sim, "do_a_backflip") is False
