"""Tests for the MuJoCo sensor adapter (backend/app/balance/sim_source.py).

Kinematic checks only (mj_forward from a known qpos, no stepping) — these
reproduce the empirical sign-verification done while building
read_attitude(): they don't just assert "some number changed", they
assert the SPECIFIC sign/direction found by actually rotating the model
and reading the sensors, so a future change that breaks that convention
fails loudly here instead of being caught (or not) three layers away in
a closed-loop test.

What this file deliberately does NOT claim: that BalanceController's
correction, applied through this sensor reading, actually reduces a real
disturbance in closed-loop physics. That was attempted and the results
were inconclusive/negative with placeholder gains — messier per-joint
coupling than a blind headless probe could cleanly resolve. See
docs/balance-controller-progress.md Phase 1 status — that verification
needs either more careful iterative tuning or the sim viewer's visual
feedback, not another blind headless guess.
"""

import math

import mujoco
import pytest

import app.resource_path as resource_path
from app.balance.sim_source import read_attitude

_MODEL_PATH = str(resource_path.repo_root() / "assets" / "ainex" / "ainex.xml")


@pytest.fixture(scope="module")
def model() -> mujoco.MjModel:
    return mujoco.MjModel.from_xml_path(_MODEL_PATH)


def _stand_data(model: mujoco.MjModel) -> mujoco.MjData:
    data = mujoco.MjData(model)
    key_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_KEY, "stand")
    mujoco.mj_resetDataKeyframe(model, data, key_id)
    return data


def _set_free_joint_tilt(data: mujoco.MjData, axis: int, theta_rad: float) -> None:
    """Rotate the free-joint root by theta_rad about world axis (0=X, 1=Y),
    leaving qpos[3:7] as the corresponding quaternion (w, x, y, z)."""
    half = theta_rad / 2.0
    quat = [math.cos(half), 0.0, 0.0, 0.0]
    quat[1 + axis] = math.sin(half)
    data.qpos[3:7] = quat


class TestUpright:
    def test_stand_pose_reads_zero_attitude(self, model):
        data = _stand_data(model)
        mujoco.mj_forward(model, data)
        attitude = read_attitude(model, data)
        assert attitude.pitch_rad == pytest.approx(0.0, abs=1e-6)
        assert attitude.roll_rad == pytest.approx(0.0, abs=1e-6)
        assert attitude.pitch_rate == pytest.approx(0.0, abs=1e-6)
        assert attitude.roll_rate == pytest.approx(0.0, abs=1e-6)


class TestPitchSign:
    def test_rotation_about_world_y_reads_as_matching_pitch(self, model):
        """Empirically verified: tilting the free joint +10 deg about
        world Y makes the up-vector's X component go positive, and
        atan2(ux, uz) recovers +10 deg directly — no sign flip needed."""
        data = _stand_data(model)
        theta = math.radians(10)
        _set_free_joint_tilt(data, axis=1, theta_rad=theta)
        mujoco.mj_forward(model, data)
        attitude = read_attitude(model, data)
        assert attitude.pitch_rad == pytest.approx(theta, abs=1e-4)
        assert attitude.roll_rad == pytest.approx(0.0, abs=1e-4)

    def test_pitch_rate_matches_qvel_about_world_y(self, model):
        data = _stand_data(model)
        data.qvel[4] = 0.3  # free joint's angular-Y dof
        mujoco.mj_forward(model, data)
        attitude = read_attitude(model, data)
        assert attitude.pitch_rate == pytest.approx(0.3, abs=1e-6)
        assert attitude.roll_rate == pytest.approx(0.0, abs=1e-6)


class TestRollSign:
    def test_rotation_about_world_x_reads_as_matching_roll(self, model):
        """Empirically verified: tilting the free joint +10 deg about
        world X makes the up-vector's Y component go NEGATIVE — the
        opposite of the pitch/Y case — so roll_rad = atan2(-uy, uz) needs
        the negation to recover +10 deg. This is the sign bug caught by
        actually running the numbers instead of assuming symmetry with
        pitch."""
        data = _stand_data(model)
        theta = math.radians(10)
        _set_free_joint_tilt(data, axis=0, theta_rad=theta)
        mujoco.mj_forward(model, data)
        attitude = read_attitude(model, data)
        assert attitude.roll_rad == pytest.approx(theta, abs=1e-4)
        assert attitude.pitch_rad == pytest.approx(0.0, abs=1e-4)

    def test_roll_rate_matches_qvel_about_world_x(self, model):
        data = _stand_data(model)
        data.qvel[3] = 0.3  # free joint's angular-X dof
        mujoco.mj_forward(model, data)
        attitude = read_attitude(model, data)
        assert attitude.roll_rate == pytest.approx(0.3, abs=1e-6)
        assert attitude.pitch_rate == pytest.approx(0.0, abs=1e-6)


class TestRateSignConsistency:
    def test_positive_rate_predicts_increasing_position_after_a_step(self, model):
        """The controller's D-term only makes sense if a positive rate
        means 'this angle is currently increasing' — checked by actually
        stepping physics, not assumed from the formulas alone."""
        data = _stand_data(model)
        data.qvel[3] = 0.5  # world +X angular velocity
        mujoco.mj_forward(model, data)
        before = read_attitude(model, data)
        for _ in range(5):
            mujoco.mj_step(model, data)
        after = read_attitude(model, data)
        assert after.roll_rad > before.roll_rad
