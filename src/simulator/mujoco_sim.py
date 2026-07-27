"""MuJoCo simulator for AiNex humanoid robot."""

import threading
import time
from pathlib import Path
from typing import Callable

import mujoco
import mujoco.viewer
import numpy as np
from loguru import logger

from validation import JOINT_LIMITS


class AiNexSimulator:
    """MuJoCo simulator wrapper for the AiNex humanoid robot.

    AiNex has 24 DOF: 6-DOF legs (×2), 5-DOF arms + gripper (×2), 2-DOF head.
    No torso joints — the body is a single rigid link.
    """

    # Short name → actuator name in the MuJoCo XML
    JOINT_NAMES = {
        # Head (2-DOF)
        "head_pan": "head_pan_act",
        "head_tilt": "head_tilt_act",
        # Left arm (5-DOF)
        "l_sho_pitch": "l_sho_pitch_act",
        "l_sho_roll": "l_sho_roll_act",
        "l_el_pitch": "l_el_pitch_act",
        "l_el_yaw": "l_el_yaw_act",
        "l_gripper": "l_gripper_act",
        # Right arm (5-DOF)
        "r_sho_pitch": "r_sho_pitch_act",
        "r_sho_roll": "r_sho_roll_act",
        "r_el_pitch": "r_el_pitch_act",
        "r_el_yaw": "r_el_yaw_act",
        "r_gripper": "r_gripper_act",
        # Left leg (6-DOF)
        "l_hip_yaw": "l_hip_yaw_act",
        "l_hip_roll": "l_hip_roll_act",
        "l_hip_pitch": "l_hip_pitch_act",
        "l_knee": "l_knee_act",
        "l_ank_pitch": "l_ank_pitch_act",
        "l_ank_roll": "l_ank_roll_act",
        # Right leg (6-DOF)
        "r_hip_yaw": "r_hip_yaw_act",
        "r_hip_roll": "r_hip_roll_act",
        "r_hip_pitch": "r_hip_pitch_act",
        "r_knee": "r_knee_act",
        "r_ank_pitch": "r_ank_pitch_act",
        "r_ank_roll": "r_ank_roll_act",
    }

    STEP_SIZE = 0.2

    # How far above its settled height to lift the floating base on reset, so the
    # robot drops and settles into a stable stand (re-stands after a fall).
    DROP_HEIGHT = 0.05

    def __init__(self, model_path: str | None = None):
        if model_path is None:
            project_root = Path(__file__).parent.parent.parent
            model_path = str(project_root / "assets" / "ainex" / "ainex.xml")

        logger.info(f"Loading MuJoCo model from: {model_path}")
        self.model = mujoco.MjModel.from_xml_path(model_path)
        self.data = mujoco.MjData(self.model)

        # Guards every mjData access (step, forward, sync, keyframe reset). The
        # MuJoCo solver stack is not thread-safe, so the physics thread, the
        # viewer sync, and command/reset paths must be mutually exclusive.
        self._lock = threading.Lock()

        self._apply_stand_keyframe()

        self._actuator_ids: dict[str, int] = {}
        for i in range(self.model.nu):
            name = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_ACTUATOR, i)
            if name:
                self._actuator_ids[name] = i

        self._joint_ids: dict[str, int] = {}
        for i in range(self.model.njnt):
            name = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_JOINT, i)
            if name:
                self._joint_ids[name] = i

        # Precompute the mesh geoms we stream to the browser viewer (/ws/sim →
        # RobotViewer.tsx). Each visual link is a single mesh geom, so we render
        # every geom independently in world space and let MuJoCo own all the
        # forward kinematics — the client just moves pre-loaded meshes to match.
        self._render_geom_ids: list[int] = []
        self._render_geoms: list[dict] = []
        for gid in range(self.model.ngeom):
            if self.model.geom_type[gid] != mujoco.mjtGeom.mjGEOM_MESH:
                continue
            mesh_id = int(self.model.geom_dataid[gid])
            if mesh_id < 0:
                continue
            mesh_name = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_MESH, mesh_id)
            # Effective color: material overrides the geom's own rgba when set.
            mat_id = int(self.model.geom_matid[gid])
            rgba = self.model.mat_rgba[mat_id] if mat_id >= 0 else self.model.geom_rgba[gid]
            # MuJoCo recenters mesh vertices at compile time and stores the
            # original offset in mesh_pos/mesh_quat. The streamed geom pose is
            # for that recentered frame, so the client must bake this offset into
            # the raw STL (v_proc = R(mesh_quat)^T @ (v_raw - mesh_pos)) or every
            # link renders displaced by its own centroid ("exploded" robot).
            # Associate the geom with the joint of its owning body so the
            # browser viewer can map a clicked mesh back to a joint (manual
            # mode). MuJoCo joint names == our short names (see ainex.xml);
            # bodies with no joint (or the root freejoint) get None.
            body_id = int(self.model.geom_bodyid[gid])
            jnt_id = int(self.model.body_jntadr[body_id])
            geom_joint: str | None = None
            if jnt_id >= 0:
                jnt_name = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_JOINT, jnt_id)
                if jnt_name in self.JOINT_NAMES:
                    geom_joint = jnt_name
            self._render_geom_ids.append(gid)
            self._render_geoms.append({
                "mesh": mesh_name,
                "rgba": [float(c) for c in rgba],
                "mesh_pos": [float(c) for c in self.model.mesh_pos[mesh_id]],
                "mesh_quat": [float(c) for c in self.model.mesh_quat[mesh_id]],  # wxyz
                "joint": geom_joint,
            })

        self._viewer_thread: threading.Thread | None = None
        self._running = False

        logger.info(
            f"AiNex simulator initialized with {self.model.nu} actuators, "
            f"{len(self._render_geom_ids)} render geoms"
        )

    def get_stand_joint_positions(self) -> dict[str, float]:
        """Return stand-keyframe joint positions (radians) without touching the live sim."""
        key_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_KEY, "stand")
        if key_id < 0:
            return {}
        temp = mujoco.MjData(self.model)
        mujoco.mj_resetDataKeyframe(self.model, temp, key_id)
        for i in range(self.model.nu):
            joint_id = self.model.actuator_trnid[i, 0]
            temp.ctrl[i] = temp.qpos[self.model.jnt_qposadr[joint_id]]
        positions: dict[str, float] = {}
        for short_name, full_name in self.JOINT_NAMES.items():
            actuator_id = self._actuator_ids.get(full_name)
            if actuator_id is not None:
                positions[short_name] = float(temp.ctrl[actuator_id])
        return positions

    def _apply_stand_keyframe(self, lift: float = 0.0) -> None:
        key_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_KEY, "stand")
        if key_id >= 0:
            # Lock so a runtime reset (reset_pose command) can't rewrite qpos/ctrl
            # while the physics thread is mid-step. Uncontended during __init__.
            with self._lock:
                mujoco.mj_resetDataKeyframe(self.model, self.data, key_id)
                if lift:
                    # Raise the floating base (qpos[0:3] = free-joint xyz; the
                    # keyframe already sets an upright quat in qpos[3:7]) above its
                    # settled height and zero velocity, so physics drops it into a
                    # stable stand. Recovers from a fallen pose, which animating
                    # joints alone cannot.
                    self.data.qpos[2] += lift
                    self.data.qvel[:] = 0.0
                # Sync ctrl targets to the keyframe joint positions so PD
                # controllers hold the pose rather than pulling toward zero.
                for i in range(self.model.nu):
                    joint_id = self.model.actuator_trnid[i, 0]
                    qpos_addr = self.model.jnt_qposadr[joint_id]
                    self.data.ctrl[i] = self.data.qpos[qpos_addr]
            logger.info(f"Applied 'stand' keyframe (lift={lift:.3f})")
        else:
            logger.warning("'stand' keyframe not found, using default pose")

    def get_joint_position(self, joint_name: str) -> float:
        full_name = self.JOINT_NAMES.get(joint_name, joint_name)
        actuator_id = self._actuator_ids.get(full_name)
        if actuator_id is None:
            raise ValueError(f"Unknown joint: {joint_name}")
        with self._lock:
            return float(self.data.ctrl[actuator_id])

    def get_physical_joint_position(self, joint_name: str) -> float:
        """Read the actual physics position from qpos (not the ctrl target)."""
        joint_id = self._joint_ids.get(joint_name)
        if joint_id is None:
            raise ValueError(f"Unknown joint: {joint_name}")
        qpos_addr = self.model.jnt_qposadr[joint_id]
        with self._lock:
            return float(self.data.qpos[qpos_addr])

    def set_joint_position(self, joint_name: str, position: float) -> None:
        full_name = self.JOINT_NAMES.get(joint_name, joint_name)
        actuator_id = self._actuator_ids.get(full_name)
        if actuator_id is None:
            raise ValueError(f"Unknown joint: {joint_name}")

        # Clamp to the joint's MECHANICAL range (jnt_range), not the tighter
        # retargeting caps in validation.JOINT_LIMITS. Those safety caps are a
        # planning-layer concern — enforced in compute_joint_targets (live
        # retarget/legacy leg mapping) and validate_waypoint. Classify mode's
        # canned poses (dab/warrior2 crouches) deliberately bypass them, so the
        # sim must render whatever it's commanded, bounded only by what the
        # hardware can physically reach.
        joint_id = int(self.model.actuator_trnid[actuator_id, 0])
        lo, hi = self.model.jnt_range[joint_id]
        if lo < hi:  # jnt_range is (0, 0) for unlimited joints — skip those
            position = max(float(lo), min(float(hi), float(position)))

        with self._lock:
            self.data.ctrl[actuator_id] = position
        # TRACE, not DEBUG: this fires once per joint per interpolation sub-step
        # (every ~20ms during a move, or ~50ms per joint during Follow), so at
        # DEBUG it drowns out actually-useful DEBUG/INFO logs (e.g. map-features'
        # leg_mode / bucket-classification lines). loguru's default level is
        # DEBUG, so TRACE is silent unless explicitly enabled (LOGURU_LEVEL=TRACE).
        logger.trace(f"Set {joint_name} to {position:.3f} rad")

    def move_joint(self, joint_name: str, delta: float) -> float:
        current = self.get_joint_position(joint_name)
        new_pos = current + delta

        if joint_name in JOINT_LIMITS:
            new_pos = JOINT_LIMITS[joint_name].clamp(new_pos)

        self.set_joint_position(joint_name, new_pos)
        logger.info(f"Moved {joint_name}: {current:.2f} -> {new_pos:.2f}")
        return new_pos

    # === HEAD CONTROLS ===
    def turn_head_left(self) -> None:
        self.move_joint("head_pan", -self.STEP_SIZE)

    def turn_head_right(self) -> None:
        self.move_joint("head_pan", self.STEP_SIZE)

    def tilt_head_up(self) -> None:
        self.move_joint("head_tilt", self.STEP_SIZE)

    def tilt_head_down(self) -> None:
        self.move_joint("head_tilt", -self.STEP_SIZE)

    # === LEFT ARM CONTROLS ===
    def move_left_arm_up(self) -> None:
        self.move_joint("l_sho_pitch", self.STEP_SIZE)

    def move_left_arm_down(self) -> None:
        self.move_joint("l_sho_pitch", -self.STEP_SIZE)

    def move_left_arm_out(self) -> None:
        self.move_joint("l_sho_roll", self.STEP_SIZE)

    def move_left_arm_in(self) -> None:
        self.move_joint("l_sho_roll", -self.STEP_SIZE)

    def bend_left_elbow(self) -> None:
        self.move_joint("l_el_yaw", -self.STEP_SIZE)

    def extend_left_elbow(self) -> None:
        self.move_joint("l_el_yaw", self.STEP_SIZE)

    def rotate_left_elbow_in(self) -> None:
        self.move_joint("l_el_pitch", -self.STEP_SIZE)

    def rotate_left_elbow_out(self) -> None:
        self.move_joint("l_el_pitch", self.STEP_SIZE)

    def open_left_gripper(self) -> None:
        self.move_joint("l_gripper", -self.STEP_SIZE)

    def close_left_gripper(self) -> None:
        self.move_joint("l_gripper", self.STEP_SIZE)

    # === RIGHT ARM CONTROLS ===
    def move_right_arm_up(self) -> None:
        self.move_joint("r_sho_pitch", self.STEP_SIZE)

    def move_right_arm_down(self) -> None:
        self.move_joint("r_sho_pitch", -self.STEP_SIZE)

    def move_right_arm_out(self) -> None:
        self.move_joint("r_sho_roll", -self.STEP_SIZE)

    def move_right_arm_in(self) -> None:
        self.move_joint("r_sho_roll", self.STEP_SIZE)

    def bend_right_elbow(self) -> None:
        self.move_joint("r_el_yaw", self.STEP_SIZE)

    def extend_right_elbow(self) -> None:
        self.move_joint("r_el_yaw", -self.STEP_SIZE)

    def rotate_right_elbow_in(self) -> None:
        self.move_joint("r_el_pitch", -self.STEP_SIZE)

    def rotate_right_elbow_out(self) -> None:
        self.move_joint("r_el_pitch", self.STEP_SIZE)

    def open_right_gripper(self) -> None:
        self.move_joint("r_gripper", self.STEP_SIZE)

    def close_right_gripper(self) -> None:
        self.move_joint("r_gripper", -self.STEP_SIZE)

    # === LEFT LEG CONTROLS ===
    def move_left_hip_forward(self) -> None:
        self.move_joint("l_hip_pitch", -self.STEP_SIZE)

    def move_left_hip_backward(self) -> None:
        self.move_joint("l_hip_pitch", self.STEP_SIZE)

    def move_left_hip_out(self) -> None:
        self.move_joint("l_hip_roll", -self.STEP_SIZE)

    def move_left_hip_in(self) -> None:
        self.move_joint("l_hip_roll", self.STEP_SIZE)

    def rotate_left_hip_in(self) -> None:
        self.move_joint("l_hip_yaw", self.STEP_SIZE)

    def rotate_left_hip_out(self) -> None:
        self.move_joint("l_hip_yaw", -self.STEP_SIZE)

    def bend_left_knee(self) -> None:
        self.move_joint("l_knee", self.STEP_SIZE)

    def extend_left_knee(self) -> None:
        self.move_joint("l_knee", -self.STEP_SIZE)

    def move_left_ankle_up(self) -> None:
        self.move_joint("l_ank_pitch", self.STEP_SIZE)

    def move_left_ankle_down(self) -> None:
        self.move_joint("l_ank_pitch", -self.STEP_SIZE)

    def roll_left_ankle_in(self) -> None:
        self.move_joint("l_ank_roll", -self.STEP_SIZE)

    def roll_left_ankle_out(self) -> None:
        self.move_joint("l_ank_roll", self.STEP_SIZE)

    # === RIGHT LEG CONTROLS ===
    def move_right_hip_forward(self) -> None:
        self.move_joint("r_hip_pitch", self.STEP_SIZE)

    def move_right_hip_backward(self) -> None:
        self.move_joint("r_hip_pitch", -self.STEP_SIZE)

    def move_right_hip_out(self) -> None:
        self.move_joint("r_hip_roll", self.STEP_SIZE)

    def move_right_hip_in(self) -> None:
        self.move_joint("r_hip_roll", -self.STEP_SIZE)

    def rotate_right_hip_in(self) -> None:
        self.move_joint("r_hip_yaw", -self.STEP_SIZE)

    def rotate_right_hip_out(self) -> None:
        self.move_joint("r_hip_yaw", self.STEP_SIZE)

    def bend_right_knee(self) -> None:
        self.move_joint("r_knee", -self.STEP_SIZE)

    def extend_right_knee(self) -> None:
        self.move_joint("r_knee", self.STEP_SIZE)

    def move_right_ankle_up(self) -> None:
        self.move_joint("r_ank_pitch", -self.STEP_SIZE)

    def move_right_ankle_down(self) -> None:
        self.move_joint("r_ank_pitch", self.STEP_SIZE)

    def roll_right_ankle_in(self) -> None:
        self.move_joint("r_ank_roll", self.STEP_SIZE)

    def roll_right_ankle_out(self) -> None:
        self.move_joint("r_ank_roll", -self.STEP_SIZE)

    # === PRESET POSES ===
    def wave(self) -> None:
        """Wave with right arm."""
        self.set_joint_position("r_sho_pitch", 0.8)
        self.set_joint_position("r_sho_roll", 0.5)
        self.set_joint_position("r_el_yaw", 1.0)
        logger.info("Executing wave pose")

    def point_forward(self) -> None:
        """Point forward with right arm."""
        self.set_joint_position("r_sho_pitch", 0.8)
        self.set_joint_position("r_sho_roll", 1.4)
        self.set_joint_position("r_el_yaw", 0.0)
        logger.info("Executing point forward pose")

    def look_around(self) -> None:
        self.set_joint_position("head_pan", -0.5)
        logger.info("Executing look around pose")

    def nod_yes(self) -> None:
        self.set_joint_position("head_tilt", 0.3)
        logger.info("Executing nod yes pose")

    def shake_no(self) -> None:
        self.set_joint_position("head_pan", -0.4)
        logger.info("Executing shake no pose")

    def reset_pose(self) -> None:
        """Re-stand the robot: place it upright slightly above the floor in the
        stand pose and let physics drop it into a settled stand. Recovers from a
        fallen state, which animating the joints alone cannot."""
        self._apply_stand_keyframe(lift=self.DROP_HEIGHT)
        logger.info("Reset: dropped into standing pose")

    def get_all_joint_states(self) -> dict[str, float]:
        states = {}
        for short_name, full_name in self.JOINT_NAMES.items():
            actuator_id = self._actuator_ids.get(full_name)
            if actuator_id is not None:
                with self._lock:
                    states[short_name] = float(self.data.ctrl[actuator_id])
        return states

    def get_joint_limits(self) -> dict[str, tuple[float, float]]:
        limits = {}
        for short_name, full_name in self.JOINT_NAMES.items():
            actuator_id = self._actuator_ids.get(full_name)
            if actuator_id is not None:
                ctrlrange = self.model.actuator_ctrlrange[actuator_id]
                limits[short_name] = (float(ctrlrange[0]), float(ctrlrange[1]))
        return limits

    # === BROWSER VIEWER STREAMING ===
    def get_render_geom_info(self) -> list[dict]:
        """Static per-geom metadata (mesh file name + color) for the browser viewer.

        The list order defines the index order of the float buffer returned by
        get_geom_poses(), so the client pairs each pose with its mesh once at
        setup time and thereafter only needs the streamed numbers.
        """
        return self._render_geoms

    def get_joint_metadata(self) -> dict:
        """Static per-joint metadata for the browser viewer's manual mode.

        Per joint (short name): rotation limits in sim radians (from
        validation.JOINT_LIMITS, the same source move_joint clamps with, falling
        back to the model's mechanical range) and the render-geom indices that
        belong to it (matching get_geom_poses() order), so the client can map
        hovered/clicked meshes to joints.
        """
        joints: dict[str, dict] = {}
        for short_name in self.JOINT_NAMES:
            limit = JOINT_LIMITS.get(short_name)
            if limit is not None:
                lo, hi = limit.min, limit.max
            else:
                jnt_id = self._joint_ids[short_name]
                lo, hi = (float(v) for v in self.model.jnt_range[jnt_id])
            joints[short_name] = {"min": lo, "max": hi, "geom_indices": []}
        for idx, geom in enumerate(self._render_geoms):
            if geom["joint"] is not None:
                joints[geom["joint"]]["geom_indices"].append(idx)
        return joints

    def get_joint_frames(self) -> list[dict]:
        """Live per-joint world frame for the browser viewer's manual mode.

        Per joint (short name): current angle (rad), world-space anchor
        (xanchor) and rotation axis (xaxis), all in the MuJoCo world frame
        (Z-up). The client uses the anchor/axis to place a rotation gizmo and
        the angle for tooltips.
        """
        with self._lock:
            # Refresh FK so xanchor/xaxis/qpos are current even when the physics
            # loop isn't stepping (same reasoning as get_geom_poses).
            mujoco.mj_forward(self.model, self.data)
            frames = []
            for short_name in self.JOINT_NAMES:
                jnt_id = self._joint_ids[short_name]
                frames.append({
                    "name": short_name,
                    "angle": float(self.data.qpos[self.model.jnt_qposadr[jnt_id]]),
                    "pos": [float(v) for v in self.data.xanchor[jnt_id]],
                    "axis": [float(v) for v in self.data.xaxis[jnt_id]],
                })
        return frames

    def get_geom_poses(self) -> bytes:
        """World-space pose of every render geom as a packed float32 buffer.

        Layout: for each geom (in get_render_geom_info() order) 7 little-endian
        float32s — [x, y, z, qw, qx, qy, qz]. MuJoCo has already resolved forward
        kinematics into geom_xpos/geom_xmat, so the browser only applies these
        transforms to pre-loaded meshes. Coordinates are MuJoCo world frame (Z-up).

        A trailing 3 float32s carry the whole-robot center of mass in the same
        world frame (MuJoCo's subtree_com for body 0, i.e. the mass-weighted
        average over every body). The browser uses this for a balance readout.
        """
        n = len(self._render_geom_ids)
        buf = np.empty(n * 7 + 3, dtype=np.float32)
        quat = np.empty(4, dtype=np.float64)
        with self._lock:
            # Refresh forward kinematics so geom_xpos/geom_xmat reflect the
            # current qpos even when the physics loop isn't stepping (e.g. the
            # native viewer thread never started / failed to launch on macOS).
            # It recomputes from state without integrating, so it's safe to
            # interleave with the stepping loop under the same lock.
            mujoco.mj_forward(self.model, self.data)
            for row, gid in enumerate(self._render_geom_ids):
                o = row * 7
                buf[o:o + 3] = self.data.geom_xpos[gid]
                mujoco.mju_mat2Quat(quat, self.data.geom_xmat[gid])
                buf[o + 3:o + 7] = quat
            buf[n * 7:n * 7 + 3] = self.data.subtree_com[0]
        return buf.tobytes()

    def start_viewer(
        self, on_close: Callable[[], None] | None = None, open_window: bool = True
    ) -> None:
        """Start the simulation loop (physics + native viewer) in one thread.

        Stepping and rendering run in the SAME thread so they never touch mjData
        concurrently — MuJoCo's solver stack is not thread-safe, and splitting
        them races even during launch_passive's own setup (→ NaN QACC / stack
        corruption / hard exit). Physics keeps stepping even if the native window
        is closed or never opens (headless), so command handling and the browser
        pose stream (/ws/sim) stay live regardless.

        Pass open_window=False to run headless on purpose — same physics loop, no
        native window (the browser viewer is unaffected).
        """
        if self._running:
            logger.warning("Simulator already running")
            return

        self._running = True
        self._viewer_thread = threading.Thread(
            target=self._run, args=(on_close, open_window), daemon=True
        )
        self._viewer_thread.start()

    def _run(
        self, on_close: Callable[[], None] | None = None, open_window: bool = True
    ) -> None:
        # timestep 0.002s × 5 steps = 0.01s sim per 0.01s sleep ≈ real-time.
        steps_per_frame = 5

        # Open the native window before the stepping loop, unlocked and on this
        # same thread — matching the original working code and coordinating with
        # mjpython's main thread without holding self._lock across it (avoids any
        # startup deadlock). No browser client exists yet, so nothing races the
        # mjData reads in its setup. Failure (e.g. no mjpython) is non-fatal — we
        # still run physics headlessly for the browser stream.
        viewer = None
        if not open_window:
            logger.info("MuJoCo viewer window disabled; running headless")
        else:
            try:
                viewer = mujoco.viewer.launch_passive(self.model, self.data)
                logger.info("MuJoCo viewer window opened")
            except Exception as e:
                logger.warning(f"Native viewer unavailable ({e}); running headless")

        logger.info("Starting MuJoCo physics loop")
        try:
            while self._running:
                with self._lock:
                    for _ in range(steps_per_frame):
                        mujoco.mj_step(self.model, self.data)
                    if viewer is not None:
                        if viewer.is_running():
                            viewer.sync()
                        else:  # window closed — keep stepping without rendering
                            viewer.close()
                            viewer = None
                            logger.info("Viewer window closed (physics continues)")
                time.sleep(0.01)
        finally:
            if viewer is not None:
                viewer.close()
            logger.info("MuJoCo physics loop stopped")

        if on_close:
            on_close()

    def stop_viewer(self) -> None:
        self._running = False
        if self._viewer_thread is not None:
            self._viewer_thread.join(timeout=2.0)
            self._viewer_thread = None

    def is_running(self) -> bool:
        return self._running


# Command mapping for LLM integration
COMMAND_MAP = {
    # Head
    "head_left": "turn_head_left",
    "head_right": "turn_head_right",
    "head_up": "tilt_head_up",
    "head_down": "tilt_head_down",
    # Left arm
    "left_arm_up": "move_left_arm_up",
    "left_arm_down": "move_left_arm_down",
    "left_arm_out": "move_left_arm_out",
    "left_arm_in": "move_left_arm_in",
    "left_elbow_bend": "bend_left_elbow",
    "left_elbow_extend": "extend_left_elbow",
    "left_elbow_rotate_in": "rotate_left_elbow_in",
    "left_elbow_rotate_out": "rotate_left_elbow_out",
    "left_gripper_open": "open_left_gripper",
    "left_gripper_close": "close_left_gripper",
    # Right arm
    "right_arm_up": "move_right_arm_up",
    "right_arm_down": "move_right_arm_down",
    "right_arm_out": "move_right_arm_out",
    "right_arm_in": "move_right_arm_in",
    "right_elbow_bend": "bend_right_elbow",
    "right_elbow_extend": "extend_right_elbow",
    "right_elbow_rotate_in": "rotate_right_elbow_in",
    "right_elbow_rotate_out": "rotate_right_elbow_out",
    "right_gripper_open": "open_right_gripper",
    "right_gripper_close": "close_right_gripper",
    # Left leg
    "left_hip_forward": "move_left_hip_forward",
    "left_hip_backward": "move_left_hip_backward",
    "left_hip_out": "move_left_hip_out",
    "left_hip_in": "move_left_hip_in",
    "left_hip_rotate_in": "rotate_left_hip_in",
    "left_hip_rotate_out": "rotate_left_hip_out",
    "left_knee_bend": "bend_left_knee",
    "left_knee_extend": "extend_left_knee",
    "left_ankle_up": "move_left_ankle_up",
    "left_ankle_down": "move_left_ankle_down",
    "left_ankle_roll_in": "roll_left_ankle_in",
    "left_ankle_roll_out": "roll_left_ankle_out",
    # Right leg
    "right_hip_forward": "move_right_hip_forward",
    "right_hip_backward": "move_right_hip_backward",
    "right_hip_out": "move_right_hip_out",
    "right_hip_in": "move_right_hip_in",
    "right_hip_rotate_in": "rotate_right_hip_in",
    "right_hip_rotate_out": "rotate_right_hip_out",
    "right_knee_bend": "bend_right_knee",
    "right_knee_extend": "extend_right_knee",
    "right_ankle_up": "move_right_ankle_up",
    "right_ankle_down": "move_right_ankle_down",
    "right_ankle_roll_in": "roll_right_ankle_in",
    "right_ankle_roll_out": "roll_right_ankle_out",
    # Preset poses
    "wave": "wave",
    "point": "point_forward",
    "look_around": "look_around",
    "nod": "nod_yes",
    "shake": "shake_no",
    "reset": "reset_pose",
}


def execute_command(simulator: AiNexSimulator, command: str) -> bool:
    method_name = COMMAND_MAP.get(command.lower().strip())
    if method_name is None:
        logger.warning(f"Unknown command: {command}")
        return False

    method = getattr(simulator, method_name, None)
    if method is None:
        logger.error(f"Method not found: {method_name}")
        return False

    method()
    return True


# Backwards compatibility aliases
ApolloSimulator = AiNexSimulator
G1Simulator = AiNexSimulator
