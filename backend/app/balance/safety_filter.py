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

import logging

import mujoco

import app.resource_path as resource_path
from app.balance.cbf import get_center_of_mass, get_support_polygon, signed_distance_to_polygon

logger = logging.getLogger(__name__)


class SafetyFilter:
    def __init__(
        self,
        model_path: str | None = None,
        num_steps: int = 8,
        buffer_steps: int = 1,
        margin_threshold: float = 0.01,
        settle_steps: int = 25,
        settle_damping: float = 50.0,
    ):
        if model_path is None:
            model_path = str(resource_path.repo_root() / "assets" / "ainex" / "ainex.xml")

        self.model = mujoco.MjModel.from_xml_path(model_path)
        self.data = mujoco.MjData(self.model)
        # 8, not 20: each step now costs a ~25-step physics settle
        # (~2.3ms) rather than a single mj_forward (~0.1ms). 20 steps
        # would be ~47ms against the follow loop's 50ms tick -- fits on
        # paper, no headroom in practice. 8 costs ~19ms.
        self.num_steps = num_steps
        # Same "extra back-off after the first unsafe step" idea as
        # CollisionChecker's buffer_steps -- stop a little before the
        # exact margin=0 knife-edge, not right at it. 1, not 2, because
        # what matters is the back-off as a FRACTION of the motion: at
        # 8 steps that is 12.5%, close to the 10% that 2-of-20 gave
        # before num_steps dropped. Left at 2 it was 25%, enough to
        # collapse a partially-safe move to "refuse everything".
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

        # Only NOW crank damping -- the reference stand above must be
        # established under the model's real dynamics. From here on this
        # shadow model is only ever asked static questions, so heavy
        # damping is free: it changes how fast equilibrium is reached,
        # not where it is. Without it the settle RINGS, and the margin
        # is read off a bouncing robot -- measured non-monotonic, with
        # plain standing reading unsafe at 400 steps.
        self.settle_steps = settle_steps
        self.model.dof_damping[:] = self.model.dof_damping * settle_damping + settle_damping

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

    def settled_joint_values(self) -> dict[str, float]:
        """Every hinge joint's angle in the settled-standing baseline.

        The correct "where the robot is right now" seed for a caller
        tracking a live stream (FollowSafetyGate) at the moment it
        starts -- taken from this filter's OWN baseline rather than
        HW_STAND_RAD, so the gate's idea of standing can't drift from
        the one every check is actually measured against.
        """
        return {
            name: float(self._settled_qpos[addr]) for name, addr in self._qpos_addr.items()
        }

    def _apply_joints(self, joints: dict[str, float]) -> None:
        for name, val in joints.items():
            addr = self._qpos_addr.get(name)
            if addr is not None:
                self.data.qpos[addr] = val

    def _settle_base(self) -> None:
        """Let the body find where it would actually rest for the pose
        currently in qpos, instead of leaving it pinned at the standing
        reference.

        This is the Phase 2.5 fix. Pinning the free-floating base made
        the filter blind to any pose whose whole point is to move it: a
        bent knee read as "the foot swings up, the CoM barely moves,
        margin fine" when in reality the leg shortens, the pelvis drops
        and tilts, and the robot goes over. That produced a verified
        false negative -- a pose measured at +0.0199 ("safe") that
        topples at every ramp rate tested.

        The joints are held at their commanded values by the actuators,
        so what settles is the BASE, not the pose being evaluated.
        """
        for i in range(self.model.nu):
            joint_id = int(self.model.actuator_trnid[i, 0])
            self.data.ctrl[i] = self.data.qpos[int(self.model.jnt_qposadr[joint_id])]
        self.data.qvel[:] = 0.0
        for _ in range(self.settle_steps):
            mujoco.mj_step(self.model, self.data)
        mujoco.mj_forward(self.model, self.data)

    def _margin_for(self, joints: dict[str, float]) -> float:
        """Margin for a full joint configuration, from a clean baseline.

        Always re-seats from `_settled_qpos` rather than continuing from
        whatever the last call left behind -- `_settle_base` integrates
        real physics, so accumulating across calls would drift.
        """
        self._reset_to_settled_baseline()
        self._apply_joints(joints)
        mujoco.mj_forward(self.model, self.data)
        self._settle_base()
        return self._margin_now()

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
        return self._margin_for(joints)

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
        moving: dict[str, tuple[float, float]] = {}
        for j, target in target_joints.items():
            if j not in self._qpos_addr:
                continue
            start = current_joints.get(j, target)
            if abs(target - start) > 1e-6:
                moving[j] = (start, target)

        if not moving:
            return dict(target_joints), 1.0, self._margin_for(current_joints)

        def pose_at(fraction: float) -> dict[str, float]:
            pose = dict(current_joints)
            for j, (start, end) in moving.items():
                pose[j] = start + fraction * (end - start)
            return pose

        last_safe_margin = self._margin_for(current_joints)
        for step in range(1, self.num_steps + 1):
            margin = self._margin_for(pose_at(step / self.num_steps))

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
                return safe_joints, safe_fraction, self._margin_for(pose_at(safe_fraction))

            last_safe_margin = margin

        return dict(target_joints), 1.0, last_safe_margin


class FollowSafetyGate:
    """Applies SafetyFilter to a continuous mimicry stream (Phase 2).

    SafetyFilter itself is stateless: each call needs to be told where
    the robot currently is. A live follow session is a stream of frames,
    so something has to carry that state between them -- this does, and
    nothing else. It tracks the pose actually commanded so far (which is
    NOT the pose requested, whenever the filter held something back) and
    measures each new frame's target against it.

    Tracking the commanded pose frame-to-frame matters for more than
    bookkeeping: checking every frame against *standing* instead would
    let the robot creep past a safe limit one individually-safe step at
    a time, since each small step looks fine in isolation.

    Known limitation carried over from Phase 1: SafetyFilter evaluates
    the free-floating base from its own settled-standing reference, not
    the live simulator's actual current base state. Joint state is now
    tracked live (that was the Phase 1 gap this closes); base drift is
    not. Fine while the robot mimics from a standing position, which is
    the only thing follow mode does today.
    """

    def __init__(self, safety_filter: SafetyFilter | None = None):
        self._filter = safety_filter if safety_filter is not None else SafetyFilter()
        self.current_joints: dict[str, float] = {}
        self.intervention_count = 0
        self.failure_count = 0
        self.last_margin: float | None = None
        self.reset()

    def reset(self) -> None:
        """Re-seed from standing and clear counters — call at the start
        of each follow session, since the robot returns to stand between
        them and stale state would misreport the first frame."""
        self.current_joints = self._filter.settled_joint_values()
        self.intervention_count = 0
        self.failure_count = 0
        self.last_margin = None

    def filter_targets(self, targets: dict[str, float]) -> tuple[dict[str, float], bool]:
        """Returns (targets_safe_to_dispatch, whether_anything_was_held_back)."""
        if not targets:
            return targets, False

        try:
            safe, fraction, margin = self._filter.check_trajectory(self.current_joints, targets)
        except Exception as exc:
            # Fail OPEN, deliberately. This gate is a new advisory layer
            # added to a live demo path that worked without it; an
            # unfiltered move is the pre-existing behavior, whereas
            # letting this raise would kill the whole follow loop.
            self.failure_count += 1
            logger.warning("Safety gate failed, passing targets through unfiltered: %s", exc)
            return targets, False

        self.current_joints.update(safe)
        self.last_margin = margin
        intervened = fraction < 1.0
        if intervened:
            self.intervention_count += 1
        return safe, intervened
