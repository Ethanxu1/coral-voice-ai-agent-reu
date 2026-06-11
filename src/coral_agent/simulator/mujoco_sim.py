"""MuJoCo simulator for AiNex humanoid robot."""

import threading
import time
from pathlib import Path
from typing import Callable

import mujoco
import mujoco.viewer
from loguru import logger

from coral_agent.validation import JOINT_LIMITS


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

    def __init__(self, model_path: str | None = None):
        if model_path is None:
            project_root = Path(__file__).parent.parent.parent.parent
            model_path = str(project_root / "assets" / "ainex" / "ainex.xml")

        logger.info(f"Loading MuJoCo model from: {model_path}")
        self.model = mujoco.MjModel.from_xml_path(model_path)
        self.data = mujoco.MjData(self.model)

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

        self._viewer_thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()

        logger.info(f"AiNex simulator initialized with {self.model.nu} actuators")

    def _apply_stand_keyframe(self) -> None:
        key_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_KEY, "stand")
        if key_id >= 0:
            mujoco.mj_resetDataKeyframe(self.model, self.data, key_id)
            # Sync ctrl targets to the keyframe joint positions so PD controllers
            # hold the pose rather than pulling toward zero.
            for i in range(self.model.nu):
                joint_id = self.model.actuator_trnid[i, 0]
                qpos_addr = self.model.jnt_qposadr[joint_id]
                self.data.ctrl[i] = self.data.qpos[qpos_addr]
            logger.info("Applied 'stand' keyframe")
        else:
            logger.warning("'stand' keyframe not found, using default pose")

    def get_joint_position(self, joint_name: str) -> float:
        full_name = self.JOINT_NAMES.get(joint_name, joint_name)
        actuator_id = self._actuator_ids.get(full_name)
        if actuator_id is None:
            raise ValueError(f"Unknown joint: {joint_name}")
        with self._lock:
            return float(self.data.ctrl[actuator_id])

    def set_joint_position(self, joint_name: str, position: float) -> None:
        full_name = self.JOINT_NAMES.get(joint_name, joint_name)
        actuator_id = self._actuator_ids.get(full_name)
        if actuator_id is None:
            raise ValueError(f"Unknown joint: {joint_name}")

        if joint_name in JOINT_LIMITS:
            position = JOINT_LIMITS[joint_name].clamp(position)

        with self._lock:
            self.data.ctrl[actuator_id] = position
        logger.debug(f"Set {joint_name} to {position:.3f} rad")

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
        self.move_joint("r_el_pitch", self.STEP_SIZE)

    def rotate_right_elbow_out(self) -> None:
        self.move_joint("r_el_pitch", -self.STEP_SIZE)

    def open_right_gripper(self) -> None:
        self.move_joint("r_gripper", self.STEP_SIZE)

    def close_right_gripper(self) -> None:
        self.move_joint("r_gripper", -self.STEP_SIZE)

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
        self._apply_stand_keyframe()
        logger.info("Reset to standing pose")

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

    def start_viewer(self, on_close: Callable[[], None] | None = None) -> None:
        if self._running:
            logger.warning("Viewer already running")
            return

        self._running = True

        def run_viewer():
            logger.info("Starting MuJoCo viewer")
            with mujoco.viewer.launch_passive(self.model, self.data) as viewer:
                while viewer.is_running() and self._running:
                    with self._lock:
                        mujoco.mj_step(self.model, self.data)
                    viewer.sync()
                    time.sleep(0.01)

            self._running = False
            logger.info("MuJoCo viewer closed")
            if on_close:
                on_close()

        self._viewer_thread = threading.Thread(target=run_viewer, daemon=True)
        self._viewer_thread.start()

    def stop_viewer(self) -> None:
        self._running = False
        if self._viewer_thread:
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
