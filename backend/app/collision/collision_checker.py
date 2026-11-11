"""Kinematic shadow-rollout collision checker for AiNex waypoints.

Loads a headless copy of the MuJoCo model and, before a waypoint is dispatched,
interpolates every joint from its current angle toward the target while
watching for self-collisions. When a new contact appears, every moving joint
is backed off to the same last-safe fraction of the motion — so motion stays
fluid (all joints stop together) and reaches as close to the target as safety
permits.

Uses mj_forward (kinematics + collision detection, no integration) so a
20-step rollout costs well under a millisecond on AiNex.

plan_path() goes further: when the straight motion would collide, it looks for
a route around through one or two intermediate poses (see its docstring).
"""

import mujoco
from app.config import AINEX_MODEL_PATH
from app.robot.hardware_angle_utils import hardware_units_to_rad
from app.robot.motions import T_POSE_PULSE
from loguru import logger

# Geom pairs whose contact is expected/harmless and must never count as a
# self-collision. The feet's outer pads (l_foot2/r_foot2) touch in normal
# narrow stances (feet close together) — that's not a real collision, so
# clamping the motion for it would wrongly block legitimate poses.
_IGNORED_CONTACT_PAIRS: frozenset[frozenset[str]] = frozenset({
    frozenset({"l_foot2", "r_foot2"}),
})


Pose = dict[str, float]

# Arm joints (shoulders and elbows): the limbs plan_path moves out of the way.
_ARM_JOINT_PREFIXES = ("l_sho", "l_el", "r_sho", "r_el")


def _path_length(path: list[Pose]) -> float:
    """Total joint travel along a path of poses (radians, summed over joints)."""
    return sum(sum(abs(b[j] - a[j]) for j in b) for a, b in zip(path, path[1:]))


class CollisionChecker:
    # Number of bisection iterations used to refine the contact boundary once
    # the coarse step-scan has bracketed it. Cheap (one mj_forward per
    # iteration) and shrinks the bracket to a small fraction of the
    # trajectory regardless of num_steps.
    _BISECTION_ITERS = 12

    def __init__(
        self,
        model_path: str | None = None,
        num_steps: int = 20,
        buffer_fraction: float = 0.02,
    ):
        if model_path is None:
            model_path = str(AINEX_MODEL_PATH)

        self.model = mujoco.MjModel.from_xml_path(model_path)
        self.data = mujoco.MjData(self.model)
        self.num_steps = num_steps
        # Extra safety back-off, as a fraction of the whole trajectory, held
        # back past the true (bisection-refined) contact boundary. Unlike a
        # step count, this margin doesn't grow if num_steps is made coarser
        # or finer.
        self.buffer_fraction = buffer_fraction

        self._qpos_addr: dict[str, int] = {}
        for i in range(self.model.njnt):
            name = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_JOINT, i)
            jtype = self.model.jnt_type[i]
            if name and jtype == mujoco.mjtJoint.mjJNT_HINGE:
                self._qpos_addr[name] = int(self.model.jnt_qposadr[i])

        stand = self.stand_joints()
        arms = [j for j in stand if j.startswith(_ARM_JOINT_PREFIXES)]
        # Clear arm positions plan_path can route through: arms down at the
        # sides (stand) and arms straight out (T-pose).
        self._arm_hubs: list[Pose] = [
            {j: stand[j] for j in arms},
            {j: hardware_units_to_rad(T_POSE_PULSE[j], j) for j in arms if j in T_POSE_PULSE},
        ]

        self._apply_stand_keyframe()
        logger.info(
            f"CollisionChecker ready — {len(self._qpos_addr)} joints, "
            f"{num_steps} steps per rollout, "
            f"{100 * buffer_fraction:.0f}% safety buffer past the true contact point"
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

    def _pose_new_contacts(
        self,
        t: float,
        moving: dict[str, tuple[float, float]],
        expected_pairs: set[frozenset[str]],
    ) -> set[frozenset[str]]:
        """Set joints to interpolation fraction `t`, resolve kinematics, and
        return any contact pairs not already present at the starting pose."""
        for j, (start, end) in moving.items():
            self.data.qpos[self._qpos_addr[j]] = start + t * (end - start)
        mujoco.mj_forward(self.model, self.data)
        return self._contact_pairs() - expected_pairs

    def _contact_pairs(self) -> set[frozenset[str]]:
        pairs: set[frozenset[str]] = set()
        for i in range(self.data.ncon):
            c = self.data.contact[i]
            g1 = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_GEOM, c.geom1) or f"g{c.geom1}"
            g2 = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_GEOM, c.geom2) or f"g{c.geom2}"
            pair = frozenset((g1, g2))
            if pair in _IGNORED_CONTACT_PAIRS:
                continue  # allowed contact — never treat as a collision
            pairs.add(pair)
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
            new_pairs = self._pose_new_contacts(t, moving, expected_pairs)
            if new_pairs:
                lo, hi = (step - 1) / self.num_steps, t
                bad_pairs = new_pairs
                for _ in range(self._BISECTION_ITERS):
                    mid = (lo + hi) / 2
                    mid_pairs = self._pose_new_contacts(mid, moving, expected_pairs)
                    if mid_pairs:
                        hi, bad_pairs = mid, mid_pairs
                    else:
                        lo = mid

                safe_fraction = max(0.0, lo - self.buffer_fraction)
                safe_joints = dict(target_joints)
                for j, (start, end) in moving.items():
                    safe_joints[j] = start + safe_fraction * (end - start)
                bad: list[str] = []
                for pair in bad_pairs:
                    names = sorted(pair)
                    if len(names) >= 2:
                        bad.append(f"{names[0]}<->{names[1]}")
                    elif names:
                        bad.append(f"{names[0]}<->self")
                return safe_joints, safe_fraction, bad

        return dict(target_joints), 1.0, []

    def plan_path(self, current_joints: Pose, target_joints: Pose) -> list[Pose] | None:
        """A self-collision-free route from ``current_joints`` to ``target_joints``.

        Returns the poses to move through in order, each a full joint dict, the
        last one being the target: just ``[target]`` when the straight motion is
        clear. When it isn't, tries routes through intermediate poses, the way a
        person would untangle the move:
          1. reorder: move one joint first or last (twist, then fold the elbow);
          2. tuck: move the arms down to the sides (stand) on the way;
          3. via an arm hub (arms at the sides, or straight out), where each half
             may use 1-2 itself.
        Every leg is checked with check_trajectory; the shortest clear route wins.
        Returns None when the target itself is in contact (no route can reach
        it) or no route is found; the caller then stops at the last safe point.
        """
        start = dict(current_joints)
        goal = {**start, **target_joints}
        self.render_pose(start)
        start_contacts = self._contact_pairs()
        self.render_pose(goal)
        if self._contact_pairs() - start_contacts:
            return None
        path = self._plan_direct(start, goal) or self._plan_via_hubs(start, goal)
        return path[1:] if path else None

    def _clear(self, a: Pose, b: Pose) -> bool:
        return self.check_trajectory(a, b)[1] >= 1.0

    def _plan_direct(self, start: Pose, goal: Pose) -> list[Pose] | None:
        """Straight, else the shortest clear reorder/tuck route; start included."""
        if self._clear(start, goal):
            return [start, goal]
        clear = [
            path for path in self._detours(start, goal)
            if all(self._clear(a, b) for a, b in zip(path, path[1:]))
        ]
        return min(clear, key=_path_length) if clear else None

    def _detours(self, start: Pose, goal: Pose) -> list[list[Pose]]:
        """Candidate routes through one or two intermediate poses."""
        detours = []
        for j in (j for j in goal if abs(goal[j] - start[j]) > 1e-6):
            detours.append([start, {**start, j: goal[j]}, goal])  # j first
            detours.append([start, {**goal, j: start[j]}, goal])  # j last
        tucked = self._arm_hubs[0]
        detours += [
            [start, {**start, **tucked}, goal],
            [start, {**goal, **tucked}, goal],
            [start, {**start, **tucked}, {**goal, **tucked}, goal],
        ]
        return detours

    def _plan_via_hubs(self, start: Pose, goal: Pose) -> list[Pose] | None:
        """Shortest route through an arm hub, each half planned directly."""
        routes = []
        for hub in self._arm_hubs:
            middle = {**goal, **hub}
            first = self._plan_direct(start, middle)
            second = first and self._plan_direct(middle, goal)
            if second:
                routes.append(first + second[1:])
        return min(routes, key=_path_length) if routes else None
