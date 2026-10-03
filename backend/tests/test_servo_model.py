"""The sim's optional "hardware" servo model: leg servos that give under load.

Step 2 of the real-robot plan (docs/cbf-whole-body-progress.md Phase 2.19).
On 2026-10-02 the real robot, on one foot, sagged ~10 deg toward the lifted
foot and held there; the default sim's servos are stiff and show none, so
it called lifts safe that were not. The "hardware" model softens the leg
servos so the sim sags like the robot, for developing balance feedback.
"""

from __future__ import annotations

import math

import mujoco
import pytest

from app.simulator.servo_model import HARDWARE_LEG_KP, LEG_SERVOS, apply_servo_model


def _kp(model, joint):
    for i in range(model.nu):
        if mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, model.actuator_trnid[i, 0]) == joint:
            return model.actuator_gainprm[i, 0], -model.actuator_biasprm[i, 1]
    raise KeyError(joint)


@pytest.fixture
def model():
    from app.simulator.mujoco_sim import AiNexSimulator

    return AiNexSimulator(servo_model="stiff").model


def test_stiff_leaves_the_model_as_authored(model):
    before = {j: _kp(model, j) for j in LEG_SERVOS | {"l_sho_pitch"}}
    apply_servo_model(model, "stiff")
    assert {j: _kp(model, j) for j in before} == before


def test_hardware_softens_every_leg_servo_and_nothing_else(model):
    arm_before = _kp(model, "l_sho_pitch")
    apply_servo_model(model, "hardware")
    for j in LEG_SERVOS:
        assert _kp(model, j) == (pytest.approx(HARDWARE_LEG_KP), pytest.approx(HARDWARE_LEG_KP)), j
    assert _kp(model, "l_sho_pitch") == arm_before


def test_unknown_model_is_an_error(model):
    with pytest.raises(ValueError):
        apply_servo_model(model, "squishy")


def test_simulator_takes_the_model_from_config(monkeypatch):
    from app import config
    from app.simulator.mujoco_sim import AiNexSimulator

    monkeypatch.setattr(config, "SIM_SERVO_MODEL", "hardware")
    assert _kp(AiNexSimulator().model, "l_hip_roll")[0] == pytest.approx(HARDWARE_LEG_KP)


def _held_lift_lean(servo_model: str) -> float:
    """Left leg raised to 20% and held, the way the hardware check did it;
    torso lean toward the lifted (left) side, degrees."""
    from app.robot.leg_lift_check import foot_fraction, lift_poses
    from app.simulator.mujoco_sim import AiNexSimulator

    sim = AiNexSimulator(servo_model=servo_model)
    m, d = sim.model, sim.data
    for _ in range(1500):
        mujoco.mj_step(m, d)
    bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "body_link")

    def lean():
        return math.degrees(math.asin(d.xmat[bid].reshape(3, 3)[1, 2]))

    base = lean()
    poses = list(lift_poses("l", 0.2))
    up = max(range(len(poses)), key=lambda k: foot_fraction(poses[k], "l"))
    for pose in poses[: up + 1]:
        for j, v in pose.items():
            sim.set_joint_position(j, v)
        for _ in range(75):  # 0.15 s per controller tick: the check's 3x slow
            mujoco.mj_step(m, d)
    for _ in range(1000):  # hold 2 s
        mujoco.mj_step(m, d)
    return lean() - base


def test_hardware_model_sags_toward_the_lifted_foot_like_the_robot():
    """Real robot: ~10 deg. Stiff sim: none. Hardware model: several deg."""
    stiff, soft = _held_lift_lean("stiff"), _held_lift_lean("hardware")
    assert abs(stiff) < 2.0, stiff
    assert soft > 4.0, soft
