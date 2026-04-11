"""MuJoCo simulator for Apptronik Apollo humanoid robot."""

import threading
import time
from pathlib import Path
from typing import Callable

import mujoco
import mujoco.viewer
from loguru import logger

from coral_agent.validation import JOINT_LIMITS


class ApolloSimulator:
    """MuJoCo simulator wrapper for the Apptronik Apollo humanoid robot.

    Apollo has independent 2-DOF head (neck yaw/pitch) and 3-DOF torso control.
    """

    # Joint name mappings for easier control
    JOINT_NAMES = {
        # Head/Neck (2-DOF: yaw and pitch)
        "neck_yaw": "neck_yaw",
        "neck_pitch": "neck_pitch",
        # Torso (3-DOF, separate from head)
        "torso_yaw": "torso_yaw",
        "torso_roll": "torso_roll",
        "torso_pitch": "torso_pitch",
        # Left arm
        "l_shoulder_aa": "l_shoulder_aa",
        "l_shoulder_fe": "l_shoulder_fe",
        "l_shoulder_ie": "l_shoulder_ie",
        "l_elbow": "l_elbow_fe",
        "l_wrist_roll": "l_wrist_roll",
        "l_wrist_yaw": "l_wrist_yaw",
        "l_wrist_pitch": "l_wrist_pitch",
        # Right arm
        "r_shoulder_aa": "r_shoulder_aa",
        "r_shoulder_fe": "r_shoulder_fe",
        "r_shoulder_ie": "r_shoulder_ie",
        "r_elbow": "r_elbow_fe",
        "r_wrist_roll": "r_wrist_roll",
        "r_wrist_yaw": "r_wrist_yaw",
        "r_wrist_pitch": "r_wrist_pitch",
        # Left leg
        "l_hip_ie": "l_hip_ie",
        "l_hip_aa": "l_hip_aa",
        "l_hip_fe": "l_hip_fe",
        "l_knee": "l_knee_fe",
        "l_ankle_ie": "l_ankle_ie",
        "l_ankle_pd": "l_ankle_pd",
        # Right leg
        "r_hip_ie": "r_hip_ie",
        "r_hip_aa": "r_hip_aa",
        "r_hip_fe": "r_hip_fe",
        "r_knee": "r_knee_fe",
        "r_ankle_ie": "r_ankle_ie",
        "r_ankle_pd": "r_ankle_pd",
    }

    # Movement step size (in radians) - discrete increments per button press
    STEP_SIZE = 0.2

    def __init__(self, model_path: str | None = None):
        """Initialize the Apollo simulator."""
        if model_path is None:
            project_root = Path(__file__).parent.parent.parent.parent
            model_path = str(project_root / "assets" / "apptronik_apollo" / "scene.xml")

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

        logger.info(f"Apollo simulator initialized with {self.model.nu} actuators")

    def _apply_stand_keyframe(self) -> None:
        """Apply the 'stand' keyframe to initialize robot pose."""
        key_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_KEY, "stand")
        if key_id >= 0:
            mujoco.mj_resetDataKeyframe(self.model, self.data, key_id)
            logger.info("Applied 'stand' keyframe")
        else:
            logger.warning("'stand' keyframe not found, using default pose")

    def get_joint_position(self, joint_name: str) -> float:
        """Get the current position of a joint."""
        full_name = self.JOINT_NAMES.get(joint_name, joint_name)
        actuator_id = self._actuator_ids.get(full_name)
        if actuator_id is None:
            raise ValueError(f"Unknown joint: {joint_name}")
        with self._lock:
            return float(self.data.ctrl[actuator_id])

    def set_joint_position(self, joint_name: str, position: float) -> None:
        """Set the target position of a joint.

        The position is clamped to joint limits to prevent invalid control values.
        """
        full_name = self.JOINT_NAMES.get(joint_name, joint_name)
        actuator_id = self._actuator_ids.get(full_name)
        if actuator_id is None:
            raise ValueError(f"Unknown joint: {joint_name}")

        # Clamp to joint limits if available
        if joint_name in JOINT_LIMITS:
            position = JOINT_LIMITS[joint_name].clamp(position)

        with self._lock:
            self.data.ctrl[actuator_id] = position
        logger.debug(f"Set {joint_name} to {position:.3f} rad")

    def move_joint(self, joint_name: str, delta: float) -> float:
        """Move a joint by a delta amount (discrete step).

        The new position is clamped to joint limits to prevent the control
        value from exceeding valid range.
        """
        current = self.get_joint_position(joint_name)
        new_pos = current + delta

        # Clamp to joint limits if available
        if joint_name in JOINT_LIMITS:
            new_pos = JOINT_LIMITS[joint_name].clamp(new_pos)

        self.set_joint_position(joint_name, new_pos)
        logger.info(f"Moved {joint_name}: {current:.2f} -> {new_pos:.2f}")
        return new_pos

    # === HEAD CONTROLS (Independent 2-DOF) ===
    def turn_head_left(self) -> None:
        """Turn head left (neck yaw)."""
        self.move_joint("neck_yaw", self.STEP_SIZE)

    def turn_head_right(self) -> None:
        """Turn head right (neck yaw)."""
        self.move_joint("neck_yaw", -self.STEP_SIZE)

    def tilt_head_up(self) -> None:
        """Tilt head up (neck pitch)."""
        self.move_joint("neck_pitch", -self.STEP_SIZE)

    def tilt_head_down(self) -> None:
        """Tilt head down (neck pitch)."""
        self.move_joint("neck_pitch", self.STEP_SIZE)

    # === TORSO CONTROLS (Separate 3-DOF) ===
    def rotate_torso_left(self) -> None:
        """Rotate torso left (torso yaw)."""
        self.move_joint("torso_yaw", -self.STEP_SIZE)

    def rotate_torso_right(self) -> None:
        """Rotate torso right (torso yaw)."""
        self.move_joint("torso_yaw", self.STEP_SIZE)

    def lean_forward(self) -> None:
        """Lean torso forward (torso pitch)."""
        self.move_joint("torso_pitch", self.STEP_SIZE)

    def lean_backward(self) -> None:
        """Lean torso backward (torso pitch)."""
        self.move_joint("torso_pitch", -self.STEP_SIZE)

    def lean_left(self) -> None:
        """Lean torso left (torso roll)."""
        self.move_joint("torso_roll", self.STEP_SIZE)

    def lean_right(self) -> None:
        """Lean torso right (torso roll)."""
        self.move_joint("torso_roll", -self.STEP_SIZE)

    # === LEFT ARM CONTROLS ===
    def move_left_arm_up(self) -> None:
        """Move left arm up (shoulder flexion)."""
        self.move_joint("l_shoulder_fe", -self.STEP_SIZE)

    def move_left_arm_down(self) -> None:
        """Move left arm down (shoulder extension)."""
        self.move_joint("l_shoulder_fe", self.STEP_SIZE)

    def move_left_arm_out(self) -> None:
        """Move left arm outward (shoulder abduction)."""
        self.move_joint("l_shoulder_aa", self.STEP_SIZE)

    def move_left_arm_in(self) -> None:
        """Move left arm inward (shoulder adduction)."""
        self.move_joint("l_shoulder_aa", -self.STEP_SIZE)

    def bend_left_elbow(self) -> None:
        """Bend left elbow."""
        self.move_joint("l_elbow", -self.STEP_SIZE)

    def extend_left_elbow(self) -> None:
        """Extend left elbow."""
        self.move_joint("l_elbow", self.STEP_SIZE)

    # === RIGHT ARM CONTROLS ===
    def move_right_arm_up(self) -> None:
        """Move right arm up (shoulder flexion)."""
        self.move_joint("r_shoulder_fe", -self.STEP_SIZE)

    def move_right_arm_down(self) -> None:
        """Move right arm down (shoulder extension)."""
        self.move_joint("r_shoulder_fe", self.STEP_SIZE)

    def move_right_arm_out(self) -> None:
        """Move right arm outward (shoulder abduction)."""
        self.move_joint("r_shoulder_aa", -self.STEP_SIZE)

    def move_right_arm_in(self) -> None:
        """Move right arm inward (shoulder adduction)."""
        self.move_joint("r_shoulder_aa", self.STEP_SIZE)

    def bend_right_elbow(self) -> None:
        """Bend right elbow."""
        self.move_joint("r_elbow", -self.STEP_SIZE)

    def extend_right_elbow(self) -> None:
        """Extend right elbow."""
        self.move_joint("r_elbow", self.STEP_SIZE)

    # === PRESET POSES ===
    def wave(self) -> None:
        """Wave with right arm."""
        self.set_joint_position("r_shoulder_fe", -0.8)
        self.set_joint_position("r_shoulder_aa", 0.3)
        self.set_joint_position("r_elbow", -1.2)
        logger.info("Executing wave pose")

    def point_forward(self) -> None:
        """Point forward with right arm."""
        self.set_joint_position("r_shoulder_fe", -0.5)
        self.set_joint_position("r_shoulder_aa", 0.0)
        self.set_joint_position("r_elbow", 0.0)
        logger.info("Executing point forward pose")

    def look_around(self) -> None:
        """Look around by moving head."""
        self.set_joint_position("neck_yaw", -0.5)
        logger.info("Executing look around pose")

    def nod_yes(self) -> None:
        """Nod head (yes gesture)."""
        self.set_joint_position("neck_pitch", 0.3)
        logger.info("Executing nod yes pose")

    def shake_no(self) -> None:
        """Shake head (no gesture)."""
        self.set_joint_position("neck_yaw", -0.4)
        logger.info("Executing shake no pose")

    def reset_pose(self) -> None:
        """Reset to standing pose."""
        self._apply_stand_keyframe()
        logger.info("Reset to standing pose")

    def get_all_joint_states(self) -> dict[str, float]:
        """Get all joint positions."""
        states = {}
        for short_name, full_name in self.JOINT_NAMES.items():
            actuator_id = self._actuator_ids.get(full_name)
            if actuator_id is not None:
                with self._lock:
                    states[short_name] = float(self.data.ctrl[actuator_id])
        return states

    def get_joint_limits(self) -> dict[str, tuple[float, float]]:
        """Get joint limits from the MuJoCo model.

        Returns:
            Dictionary mapping joint names to (min, max) tuples
        """
        limits = {}
        for short_name, full_name in self.JOINT_NAMES.items():
            actuator_id = self._actuator_ids.get(full_name)
            if actuator_id is not None:
                ctrlrange = self.model.actuator_ctrlrange[actuator_id]
                limits[short_name] = (float(ctrlrange[0]), float(ctrlrange[1]))
        return limits

    def start_viewer(self, on_close: Callable[[], None] | None = None) -> None:
        """Start the MuJoCo viewer in a separate thread."""
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
        """Stop the viewer thread."""
        self._running = False
        if self._viewer_thread:
            self._viewer_thread.join(timeout=2.0)
            self._viewer_thread = None

    def is_running(self) -> bool:
        """Check if the viewer is running."""
        return self._running


# Command mapping for LLM integration
COMMAND_MAP = {
    # Head commands (independent 2-DOF)
    "head_left": "turn_head_left",
    "head_right": "turn_head_right",
    "head_up": "tilt_head_up",
    "head_down": "tilt_head_down",
    # Torso commands (separate from head)
    "torso_left": "rotate_torso_left",
    "torso_right": "rotate_torso_right",
    "lean_forward": "lean_forward",
    "lean_backward": "lean_backward",
    "lean_left": "lean_left",
    "lean_right": "lean_right",
    # Left arm
    "left_arm_up": "move_left_arm_up",
    "left_arm_down": "move_left_arm_down",
    "left_arm_out": "move_left_arm_out",
    "left_arm_in": "move_left_arm_in",
    "left_elbow_bend": "bend_left_elbow",
    "left_elbow_extend": "extend_left_elbow",
    # Right arm
    "right_arm_up": "move_right_arm_up",
    "right_arm_down": "move_right_arm_down",
    "right_arm_out": "move_right_arm_out",
    "right_arm_in": "move_right_arm_in",
    "right_elbow_bend": "bend_right_elbow",
    "right_elbow_extend": "extend_right_elbow",
    # Preset poses
    "wave": "wave",
    "point": "point_forward",
    "look_around": "look_around",
    "nod": "nod_yes",
    "shake": "shake_no",
    "reset": "reset_pose",
}


def execute_command(simulator: ApolloSimulator, command: str) -> bool:
    """Execute a command on the simulator."""
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


# Backwards compatibility alias
G1Simulator = ApolloSimulator
