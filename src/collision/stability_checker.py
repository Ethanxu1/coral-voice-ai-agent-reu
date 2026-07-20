"""Dynamics-based fall check for AiNex moves.

CollisionChecker answers "does this motion self-collide?" kinematically
(mj_forward, no gravity). This module answers the question it can't: "does this
pose make the robot FALL OVER?" — which needs real dynamics, because with
kinematics alone the free-floating base stays pinned wherever the keyframe put
it and the head height never changes no matter how unstable the stance is.

A headless copy of the model is driven through its position actuators toward
the target pose and stepped forward under gravity + floor contact for a fixed
settle time (simulated seconds — the wall-clock cost is ~tens of ms). If the
head body settles below a fraction of its standing height, the robot toppled
and the move is reported as a fall: callers block it entirely (0% of the move)
rather than clamping, since there is no "safe fraction" of falling over.

Same physics approach as collision/leg_bucket_test.py's _DynamicsModel,
promoted here so the live server can use it per-move.
"""

from __future__ import annotations

import os
from pathlib import Path

import mujoco
from loguru import logger

_HEAD_BODY_NAME = "head_tilt_link"

# Simulated seconds to settle under gravity before measuring. 1.5s matches
# leg_bucket_test's empirically-sufficient settle window.
_SETTLE_SECONDS = 1.5

# A pose "fell" when the settled head height drops below this fraction of the
# settled STAND head height. Calibration points (from leg_bucket_test runs):
# stand head_z ≈ 0.358, deepest legitimate crouch ("low" bucket) ≈ 0.322 (~0.90x),
# fallen flat ≈ 0.1 or less (~0.3x) — 0.70 cleanly separates the two regimes.
# Overridable via FALL_HEAD_HEIGHT_FRAC for tuning without a code change.
_DEFAULT_FALL_HEAD_FRAC = float(os.getenv("FALL_HEAD_HEIGHT_FRAC", "0.70"))


class StabilityChecker:
    def __init__(
        self,
        model_path: str | None = None,
        settle_seconds: float = _SETTLE_SECONDS,
        fall_head_frac: float = _DEFAULT_FALL_HEAD_FRAC,
    ):
        if model_path is None:
            # stability_checker.py lives at src/coral_agent/collision/ — four
            # levels up from the project root.
            project_root = Path(__file__).parent.parent.parent
            model_path = str(project_root / "assets" / "ainex" / "ainex.xml")

        self.model = mujoco.MjModel.from_xml_path(model_path)
        self.data = mujoco.MjData(self.model)
        self.fall_head_frac = fall_head_frac
        self.settle_steps = max(1, round(settle_seconds / float(self.model.opt.timestep)))

        self._qpos_addr: dict[str, int] = {}
        self._actuator_id: dict[str, int] = {}
        for i in range(self.model.njnt):
            name = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_JOINT, i)
            if name and self.model.jnt_type[i] == mujoco.mjtJoint.mjJNT_HINGE:
                self._qpos_addr[name] = int(self.model.jnt_qposadr[i])
                act_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_ACTUATOR, f"{name}_act")
                if act_id >= 0:
                    self._actuator_id[name] = act_id

        self._head_body_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, _HEAD_BODY_NAME)
        if self._head_body_id < 0:
            raise RuntimeError(f"body '{_HEAD_BODY_NAME}' not found in {model_path}")

        key_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_KEY, "stand")
        mujoco.mj_resetDataKeyframe(self.model, self.data, key_id)
        self._stand_joints = {n: float(self.data.qpos[a]) for n, a in self._qpos_addr.items()}

        # Baseline: where the head settles when simply holding stand.
        self.stand_head_z = self._settle({})
        logger.info(
            f"StabilityChecker ready — stand head_z={self.stand_head_z:.4f}, "
            f"fall threshold {fall_head_frac:.0%} ({self.fall_threshold_z:.4f}), "
            f"{self.settle_steps} steps per settle"
        )

    @property
    def fall_threshold_z(self) -> float:
        return self.fall_head_frac * self.stand_head_z

    def _settle(
        self,
        target_joints: dict[str, float],
        current_joints: dict[str, float] | None = None,
    ) -> float:
        """Reset to the stand keyframe (optionally overridden to the robot's
        current joints), drive every actuator toward stand+targets, step under
        gravity + floor contact for the settle window, and return the head's
        settled world Z."""
        key_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_KEY, "stand")
        mujoco.mj_resetDataKeyframe(self.model, self.data, key_id)  # qpos/qvel/ctrl reset
        if current_joints:
            for name, val in current_joints.items():
                addr = self._qpos_addr.get(name)
                if addr is not None:
                    self.data.qpos[addr] = val

        ctrl_targets = dict(self._stand_joints)
        ctrl_targets.update(target_joints)
        for name, val in ctrl_targets.items():
            act_id = self._actuator_id.get(name)
            if act_id is not None:
                self.data.ctrl[act_id] = val

        for _ in range(self.settle_steps):
            mujoco.mj_step(self.model, self.data)
        return float(self.data.xpos[self._head_body_id][2])

    def check_fall(
        self,
        target_joints: dict[str, float],
        current_joints: dict[str, float] | None = None,
    ) -> dict:
        """Shadow-settle the move under real physics and report whether it topples.

        Returns {"fell": bool, "head_z": float, "stand_head_z": float,
        "threshold_z": float}. `current_joints` (the live sim's pose) seeds the
        starting qpos so the transition being checked matches what will actually
        be dispatched; targets not covered keep their stand value.
        """
        head_z = self._settle(target_joints, current_joints)
        fell = head_z < self.fall_threshold_z
        return {
            "fell": fell,
            "head_z": round(head_z, 4),
            "stand_head_z": round(self.stand_head_z, 4),
            "threshold_z": round(self.fall_threshold_z, 4),
        }
