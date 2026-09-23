"""CBF-style safety filter for mimicry targets (Phase 1 of
docs/cbf-whole-body-progress.md).

Not a full optimization-based CBF (no QP solver, no velocity/torque-level
formulation) -- a scoped, buildable first version that captures the same
core idea: given a target pose that might be unsafe, find the point
along the path from the current pose that stays safe, closest to what
was actually requested, rather than either blocking the whole move
(StabilityChecker's approach) or letting an unsafe move through
untouched (today's live-follow path, which has no check at all).

Architecture deliberately mirrors CollisionChecker
(backend/app/collision/collision_checker.py) exactly -- its own headless
model/data, its own qpos-address map, step-by-step interpolation via
mj_forward, back off to the last safe fraction when a step goes unsafe.
That module already proved this pattern works and is fast (a 20-step
kinematic rollout costs well under a millisecond) for an analogous
problem (self-collision instead of stability); reusing it here rather
than inventing a new architecture.

Why mj_forward alone is enough here, unlike cbf.py's own Phase 0
finding that a fresh keyframe reset needs real dynamics stepping (~750
steps) before its contact sensors are trustworthy: that finding was
about a robot dropping from a keyframe onto the floor for the first
time -- a genuine physics settling process. This filter instead starts
from an ALREADY-realistic, already-settled qpos (the live robot's
actual current state) and asks a well-posed kinematic question about a
nearby candidate configuration -- "which feet touch the ground in THIS
configuration" -- which a single mj_forward answers correctly (verified
empirically: feeding a pre-settled qpos through mj_forward alone
reproduces the same contact pattern 750 real dynamics steps produce).
"""

from __future__ import annotations

import mujoco

import app.resource_path as resource_path
from app.balance.cbf import get_center_of_mass, get_support_polygon, signed_distance_to_polygon


class SafetyFilter:
    def __init__(
        self,
        model_path: str | None = None,
        num_steps: int = 20,
        buffer_steps: int = 2,
        margin_threshold: float = 0.01,
    ):
        if model_path is None:
            model_path = str(resource_path.repo_root() / "assets" / "ainex" / "ainex.xml")

        self.model = mujoco.MjModel.from_xml_path(model_path)
        self.data = mujoco.MjData(self.model)
        self.num_steps = num_steps
        # Same "extra back-off after the first unsafe step" idea as
        # CollisionChecker's buffer_steps -- stop a little before the
        # exact margin=0 knife-edge, not right at it.
        self.buffer_steps = buffer_steps
        # Required stability margin (meters) to count as "safe" -- not
        # 0.0. This robot's own foot pads are only a few cm across (see
        # cbf.py), so a razor-thin positive margin is still practically
        # risky; 1cm is a deliberately conservative starting buffer, not
        # a measured/tuned value yet.
        self.margin_threshold = margin_threshold

        self._qpos_addr: dict[str, int] = {}
        for i in range(self.model.njnt):
            name = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_JOINT, i)
            jtype = self.model.jnt_type[i]
            if name and jtype == mujoco.mjtJoint.mjJNT_HINGE:
                self._qpos_addr[name] = int(self.model.jnt_qposadr[i])

        # The free-floating base (position + orientation) is NOT a hinge
        # joint, so it's never in `_qpos_addr` or any `joints` dict a
        # caller passes in -- callers only ever specify leg/arm/head
        # angles. A single mj_forward correctly detects contact for a
        # candidate pose ONLY if it starts from an already-realistic,
        # already-settled configuration (verified empirically -- see
        # module docstring); the raw `stand` keyframe's qpos is NOT
        # that (its feet aren't quite touching yet, resolved by gravity
        # during real settling). So: settle once, for real, here at
        # construction time, and use THIS as the reference baseline
        # every check starts from -- not the raw keyframe.
        self._apply_stand_keyframe()
        for _ in range(750):  # ~1.5s -- see cbf.py's own settle-time finding
            mujoco.mj_step(self.model, self.data)
        self._settled_qpos = self.data.qpos.copy()

    def _apply_stand_keyframe(self) -> None:
        key_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_KEY, "stand")
        if key_id >= 0:
            mujoco.mj_resetDataKeyframe(self.model, self.data, key_id)

    def _reset_to_settled_baseline(self) -> None:
        """Restore the one-time settled reference qpos (base position AND
        every joint) -- the correct starting point for a single-call
        mj_forward shadow check, unlike the raw stand keyframe."""
        self.data.qpos[:] = self._settled_qpos
        self.data.qvel[:] = 0.0

    def _apply_joints(self, joints: dict[str, float]) -> None:
        for name, val in joints.items():
            addr = self._qpos_addr.get(name)
            if addr is not None:
                self.data.qpos[addr] = val

    def _margin_now(self) -> float:
        """Stability margin for whatever qpos self.data currently holds.
        Caller must have already called mj_forward this tick."""
        com_x, com_y, _com_z = get_center_of_mass(self.data)
        polygon = get_support_polygon(self.model, self.data)
        return signed_distance_to_polygon((com_x, com_y), polygon)

    def check_pose(self, joints: dict[str, float]) -> float:
        """Stability margin a given full joint configuration would have,
        starting from the settled-standing baseline for any joint not
        present in `joints` (see _reset_to_settled_baseline) -- mirrors
        CollisionChecker.render_pose's convention (stand as the default
        for anything unspecified), for the same reason: a caller
        checking one candidate pose in isolation, not a trajectory."""
        self._reset_to_settled_baseline()
        self._apply_joints(joints)
        mujoco.mj_forward(self.model, self.data)
        return self._margin_now()

    def check_trajectory(
        self,
        current_joints: dict[str, float],
        target_joints: dict[str, float],
    ) -> tuple[dict[str, float], float, float]:
        """Interpolate current -> target, stopping at the last safe
        fraction if stability margin drops below margin_threshold along
        the way. Returns (safe_target_joints, safe_fraction, final_margin).

        safe_fraction is 1.0 when the full motion stays safe throughout;
        otherwise every moving joint is scaled back to the same
        last-safe fraction (fluid, all-joints-together motion, same as
        CollisionChecker -- not each joint independently clamped).
        `current_joints` is layered on top of the settled-standing
        baseline (base position included, see
        _reset_to_settled_baseline) for any joint it doesn't cover --
        Phase 2 (wiring this into the live-follow path) should instead
        seed the free-floating base from the real simulator's actual
        current qpos, not this static settled reference; that's a
        known, documented limitation of this first version, not an
        oversight.
        """
        self._reset_to_settled_baseline()
        self._apply_joints(current_joints)
        mujoco.mj_forward(self.model, self.data)

        moving: dict[str, tuple[float, float]] = {}
        for j, target in target_joints.items():
            if j not in self._qpos_addr:
                continue
            start = current_joints.get(j, target)
            if abs(target - start) > 1e-6:
                moving[j] = (start, target)

        if not moving:
            return dict(target_joints), 1.0, self._margin_now()

        last_safe_margin = self._margin_now()
        for step in range(1, self.num_steps + 1):
            t = step / self.num_steps
            for j, (start, end) in moving.items():
                self.data.qpos[self._qpos_addr[j]] = start + t * (end - start)
            mujoco.mj_forward(self.model, self.data)
            margin = self._margin_now()

            if margin < self.margin_threshold:
                safe_step = max(0, step - 1 - self.buffer_steps)
                safe_fraction = safe_step / self.num_steps
                safe_joints = dict(target_joints)
                for j, (start, end) in moving.items():
                    safe_joints[j] = start + safe_fraction * (end - start)
                # Re-evaluate at the actual returned fraction, not the
                # last-sampled step's margin -- buffer_steps means these
                # can differ, and a caller relying on this number should
                # see what the returned pose really measures.
                for name, val in safe_joints.items():
                    addr = self._qpos_addr.get(name)
                    if addr is not None:
                        self.data.qpos[addr] = val
                mujoco.mj_forward(self.model, self.data)
                return safe_joints, safe_fraction, self._margin_now()

            last_safe_margin = margin

        return dict(target_joints), 1.0, last_safe_margin
