"""Kinematic shadow-rollout collision checker for AiNex waypoints.

Loads a headless copy of the MuJoCo model and, before a waypoint is dispatched,
interpolates every joint from its current angle toward the target while
watching for self-collisions. When a new contact appears, every moving joint
is backed off to the same last-safe fraction of the motion — so motion stays
fluid (all joints stop together) and reaches as close to the target as safety
permits.

Uses mj_forward (kinematics + collision detection, no integration) so a
20-step rollout costs well under a millisecond on AiNex.
"""

from pathlib import Path

import mujoco
from loguru import logger

class CollisionChecker:
    def __init__(
        self,
        model_path: str | None = None,
        num_steps: int = 20,
        buffer_steps: int = 2,
    ):
        if model_path is None:
            # collision_checker.py lives at src/coral_agent/collision/ — four
            # levels up from the project root.
            project_root = Path(__file__).parent.parent.parent
            model_path = str(project_root / "assets" / "ainex" / "ainex.xml")

        self.model = mujoco.MjModel.from_xml_path(model_path)
        self.data = mujoco.MjData(self.model)
        self.num_steps = num_steps
        # Extra safety back-off: after locating the first colliding step, back
        # off this many additional interpolation steps. With num_steps=20 and
        # buffer_steps=2, motion stops ~10% of the way BEFORE first contact.
        self.buffer_steps = buffer_steps

        self._qpos_addr: dict[str, int] = {}
        for i in range(self.model.njnt):
            name = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_JOINT, i)
            jtype = self.model.jnt_type[i]
            if name and jtype == mujoco.mjtJoint.mjJNT_HINGE:
                self._qpos_addr[name] = int(self.model.jnt_qposadr[i])

        self._apply_stand_keyframe()
        logger.info(
            f"CollisionChecker ready — {len(self._qpos_addr)} joints, "
            f"{num_steps} steps per rollout, {buffer_steps}-step safety buffer "
            f"(~{100 * buffer_steps / num_steps:.0f}% extra back-off)"
        )

    def _apply_stand_keyframe(self) -> None:
        key_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_KEY, "stand")
        if key_id >= 0:
            mujoco.mj_resetDataKeyframe(self.model, self.data, key_id)

    def stand_joints(self) -> dict[str, float]:
        """Joint angles (radians) of the model's ``stand`` keyframe."""
        self._apply_stand_keyframe()
        return {
            name: float(self.data.qpos[addr])
            for name, addr in self._qpos_addr.items()
        }

    def _apply_joints(self, joints: dict[str, float]) -> None:
        for name, val in joints.items():
            addr = self._qpos_addr.get(name)
            if addr is not None:
                self.data.qpos[addr] = val

    def render_pose(self, joints: dict[str, float]) -> None:
        """Set self.data to `joints` (stand keyframe as the baseline for any
        joint not in the dict) and resolve forward kinematics — for callers
        (e.g. collision_test.py) that want to sync a live viewer to a result
        without reaching into the stand/apply-joints internals themselves.
        """
        self._apply_stand_keyframe()
        self._apply_joints(joints)
        mujoco.mj_forward(self.model, self.data)

    def _contact_pairs(self) -> set[frozenset[str]]:
        pairs: set[frozenset[str]] = set()
        for i in range(self.data.ncon):
            c = self.data.contact[i]
            g1 = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_GEOM, c.geom1) or f"g{c.geom1}"
            g2 = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_GEOM, c.geom2) or f"g{c.geom2}"
            pairs.add(frozenset((g1, g2)))
        return pairs

    def check_trajectory(
        self,
        current_joints: dict[str, float],
        target_joints: dict[str, float],
    ) -> tuple[dict[str, float], float, list[str]]:
        """Rollout the interpolated motion and return safe targets.

        Returns (safe_target_joints, safe_fraction, bad_pair_descriptions).
        safe_fraction is 1.0 when the full motion is safe; otherwise every
        moving joint is scaled back to the same last-safe fraction.
        """
        self._apply_stand_keyframe()
        self._apply_joints(current_joints)
        mujoco.mj_forward(self.model, self.data)
        expected_pairs = self._contact_pairs()

        moving: dict[str, tuple[float, float]] = {}
        for j, target in target_joints.items():
            if j not in self._qpos_addr:
                continue
            start = current_joints.get(j, target)
            if abs(target - start) > 1e-6:
                moving[j] = (start, target)

        if not moving:
            return dict(target_joints), 1.0, []

        for step in range(1, self.num_steps + 1):
            t = step / self.num_steps
            for j, (start, end) in moving.items():
                self.data.qpos[self._qpos_addr[j]] = start + t * (end - start)
            mujoco.mj_forward(self.model, self.data)

            new_pairs = self._contact_pairs() - expected_pairs
            if new_pairs:
                safe_step = max(0, step - 1 - self.buffer_steps)
                safe_fraction = safe_step / self.num_steps
                safe_joints = dict(target_joints)
                for j, (start, end) in moving.items():
                    safe_joints[j] = start + safe_fraction * (end - start)
                bad: list[str] = []
                for pair in new_pairs:
                    names = sorted(pair)
                    if len(names) >= 2:
                        bad.append(f"{names[0]}<->{names[1]}")
                    elif names:
                        bad.append(f"{names[0]}<->self")
                return safe_joints, safe_fraction, bad

        return dict(target_joints), 1.0, []
