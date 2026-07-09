"""FastAPI server for the Coral AI agent with MuJoCo simulation."""

import asyncio
import base64
import json
import math
import os
import re
import sys
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Load environment variables before initializing Langfuse
load_dotenv()

from langfuse import observe, get_client, Langfuse, propagate_attributes
from langfuse.openai import openai
import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pydantic import BaseModel

from coral_agent.config import LLM_MODEL
from coral_agent.follow_controller import FollowController
from coral_agent.primitives import (
    get_parameterized_primitive,
    get_primitive,
    get_primitives_metadata,
    resolve_primitive,
)


def convert_state_to_degrees(state: dict[str, float]) -> dict[str, float]:
    return {joint: round(math.degrees(value), 1) for joint, value in state.items()}


from coral_agent.robot.angle_utils import rad_to_servo_units, speed_to_duration_ms
from coral_agent.robot.hardware_angle_utils import hardware_units_to_rad
from coral_agent.robot.hardware_controller import AiNexHardwareController
from coral_agent.robot.interface import ServoCommand
from coral_agent.robot.servo_config import SERVO_ID_MAP
from coral_agent.robot.sim_controller import SimController
from coral_agent.simulator import AiNexSimulator
from coral_agent.simulator.mujoco_sim import COMMAND_MAP, execute_command
from coral_agent.state import (
    StateManager,
)
from coral_agent.validation import (
    ValidationResult,
    describe_joint_state,
    validate_motion_sign,
    validate_waypoint,
)

# Setup recordings directory
RECORDINGS_DIR = Path(__file__).parent.parent.parent / "recordings"
RECORDINGS_DIR.mkdir(exist_ok=True)
PROMPTS_DIR = Path(__file__).parent / "prompts"

# Global simulator and dispatcher instances. In robot mode both dispatchers are
# set: sim_dispatcher animates the MuJoCo viewer (so we can see what the code
# wants the robot to do) while hardware_dispatcher drives the physical robot.
# In sim mode only sim_dispatcher is set.
simulator: AiNexSimulator | None = None
sim_dispatcher: SimController | None = None
hardware_dispatcher: AiNexHardwareController | None = None
robot_mode: str = "sim"
follow_controller: FollowController | None = None


def _get_robot_state() -> dict[str, float]:
    """Return current joint states — hardware in robot mode, simulator otherwise."""
    if hardware_dispatcher is not None:
        try:
            return hardware_dispatcher.get_joint_states()
        except Exception as e:
            logger.debug(f"Hardware joint-state read failed, falling back to sim: {e}")
    if simulator is not None:
        return simulator.get_all_joint_states()
    return {}


def _sync_sim_to_hardware() -> None:
    """Copy the physical robot's current joint positions into the simulator
    so the viewer starts mirroring the real robot's pose."""
    if simulator is None or hardware_dispatcher is None:
        return
    try:
        physical_state = hardware_dispatcher.get_joint_states()
    except Exception as e:
        logger.warning(f"Could not read physical joint states for sim sync: {e}")
        return
    synced = 0
    for joint, rad in physical_state.items():
        if joint in simulator.JOINT_NAMES:
            simulator.set_joint_position(joint, rad)
            synced += 1
    logger.info(f"Synced simulator to {synced} physical joint positions")


_router_prompt_cache: str | None = None


def get_router_prompt() -> str:
    global _router_prompt_cache
    if _router_prompt_cache is None:
        _router_prompt_cache = (Path(__file__).parent / "prompts" / "router.md").read_text(encoding="utf-8")
    return _router_prompt_cache


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan - start/stop simulator and Langfuse."""
    global simulator, sim_dispatcher, hardware_dispatcher, robot_mode, follow_controller

    robot_mode = os.getenv("ROBOT_MODE", "sim")

    # Always start the MuJoCo simulator — in robot mode it provides a visualization
    # of what the code wants the robot to do, so we can compare to the physical motion.
    logger.info("Starting AiNex MuJoCo simulator...")
    simulator = AiNexSimulator()
    simulator.start_viewer()
    sim_dispatcher = SimController(simulator)

    if robot_mode in ("robot", "hardware"):
        logger.info(f"ROBOT MODE — targeting physical robot at {os.getenv('ROBOT_IP', '192.168.8.219')}")
        hardware_dispatcher = AiNexHardwareController()
        # Mirror physical pose into sim so the viewer starts where the robot actually is.
        _sync_sim_to_hardware()

    logger.info(f"Robot dispatchers initialized (mode={robot_mode})")

    follow_controller = FollowController(dispatch_servo_commands)

    langfuse_client = Langfuse()
    logger.info("Langfuse tracing initialized")

    logger.info("Pre-loading Whisper STT model...")
    _get_whisper_model()
    logger.info("Whisper model ready.")

    yield

    if simulator is not None:
        logger.info("Stopping AiNex simulator...")
        simulator.stop_viewer()

    logger.info("Flushing Langfuse traces...")
    langfuse_client.flush()


app = FastAPI(title="Coral AI Agent", lifespan=lifespan)

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CommandRequest(BaseModel):
    """Request body for manual commands."""

    command: str


class CommandResponse(BaseModel):
    """Response for command execution."""

    success: bool
    message: str
    joint_states: dict[str, float] | None = None


class ChatMessage(BaseModel):
    """Chat message structure."""

    role: str  # "user" or "assistant"
    content: str
    commands: list[str] | None = None


# Store connected websocket clients
connected_clients: set[WebSocket] = set()

_whisper_model = None


def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        logger.info("Loading Whisper model (base)...")
        _whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
        logger.info("Whisper model loaded.")
    return _whisper_model


def transcribe_audio(audio_bytes: bytes) -> str:
    model = _get_whisper_model()
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name
    try:
        segments, _ = model.transcribe(tmp_path, language="en", no_speech_threshold=0.6)
        return " ".join(
            seg.text.strip() for seg in segments if seg.no_speech_prob < 0.6
        ).strip()
    finally:
        Path(tmp_path).unlink(missing_ok=True)


class ConversationRecorder:
    """Records conversation interactions to a JSON file for debugging."""

    def __init__(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.filepath = RECORDINGS_DIR / f"conversation_{timestamp}.json"
        self.interactions: list[dict] = []
        self.start_time = datetime.now().isoformat()
        logger.info(f"Recording conversation to: {self.filepath}")

    def log_interaction(
        self,
        user_message: str,
        assistant_response: str,
        waypoints_extracted: list[dict],
        waypoints_executed: list[dict],
        router_response: dict | None = None,
    ) -> None:
        """Log a single interaction (user message + assistant response).

        Args:
            user_message: The user's input message
            assistant_response: The verbal response to the user
            waypoints_extracted: Waypoint data (primitive, angle, direction, speed, joints_radians, joints_degrees)
            waypoints_executed: Execution results from the simulator
            router_response: The motion planner's raw JSON response
        """
        interaction = {
            "timestamp": datetime.now().isoformat(),
            "user": user_message,
            "assistant": assistant_response,
            "router_decision": router_response,
            "waypoints": waypoints_extracted,
            "execution": waypoints_executed,
        }
        self.interactions.append(interaction)
        self._save()

    def _save(self) -> None:
        """Save the recording to disk."""
        data = {
            "session_start": self.start_time,
            "session_end": datetime.now().isoformat(),
            "interaction_count": len(self.interactions),
            "interactions": self.interactions,
        }
        with open(self.filepath, "w") as f:
            json.dump(data, f, indent=2)
        logger.debug(f"Saved {len(self.interactions)} interactions to {self.filepath}")


class Waypoint:
    def __init__(
        self,
        joints: dict[str, float],
        speed: float = 1.0,
        primitive_name: str | None = None,
        angle: float | None = None,
        direction: str | None = None,
    ):
        self.joints = joints
        self.speed = max(0.1, min(speed, 8.0))
        self.primitive_name = primitive_name
        self.angle = angle
        self.direction = direction
        self.validation_result: ValidationResult | None = None




async def dispatch_servo_commands(commands: list[ServoCommand]) -> None:
    """Send a batch of ServoCommands to both sim and hardware dispatchers concurrently.

    In sim mode only sim_dispatcher is set; in robot mode both fire concurrently.
    Shared by the motion planner's execute_waypoints and the vision follow loop.
    """
    if not commands:
        return
    dispatches = []
    if sim_dispatcher is not None:
        dispatches.append(asyncio.to_thread(sim_dispatcher.send_commands, commands))
    if hardware_dispatcher is not None:
        dispatches.append(asyncio.to_thread(hardware_dispatcher.send_commands, commands))
    if dispatches:
        await asyncio.gather(*dispatches)


async def execute_waypoints(
    simulator: AiNexSimulator, waypoints: list[Waypoint]
) -> list[dict]:
    """Execute a sequence of waypoints through the hardware abstraction layer.

    Each waypoint is converted to ServoCommands (Hiwonder units + duration_ms)
    and dispatched to the controller, which handles concurrent joint interpolation.
    Sequential waypoints run one after the other.

    Returns a list of executed waypoint info.
    """
    executed = []

    for i, waypoint in enumerate(waypoints):
        duration_ms = speed_to_duration_ms(waypoint.speed)
        commands = []
        for joint_name, rad in waypoint.joints.items():
            servo_id = SERVO_ID_MAP.get(joint_name)
            if servo_id is None:
                logger.warning(f"No servo ID mapping for joint: {joint_name}")
                continue
            commands.append(ServoCommand(
                servo_id=servo_id,
                position=rad_to_servo_units(rad),
                duration_ms=duration_ms,
            ))

        await dispatch_servo_commands(commands)

        executed.append(
            {
                "waypoint_index": i,
                "primitive_name": waypoint.primitive_name,
                "angle": waypoint.angle,
                "joints": waypoint.joints,
                "speed": waypoint.speed,
            }
        )
        logger.info(
            f"Executed waypoint {i}: {waypoint.primitive_name or 'direct'} "
            f"angle={waypoint.angle} speed={waypoint.speed} duration_ms={duration_ms}"
        )

    return executed


async def execute_parallel_tracks(
    simulator: AiNexSimulator,
    tracks: list[list[Waypoint]],
) -> list[dict]:
    """Execute multiple waypoint tracks concurrently using asyncio.gather.

    Tracks should operate on disjoint joint sets to avoid conflicts.
    """
    results = await asyncio.gather(
        *[execute_waypoints(simulator, track) for track in tracks]
    )
    return [wp for track_result in results for wp in track_result]


@app.post("/command", response_model=CommandResponse)
async def execute_manual_command(request: CommandRequest) -> CommandResponse:
    """Execute a manual robot command on the simulator and (in robot mode) the physical robot."""
    if simulator is None:
        return CommandResponse(
            success=False,
            message="Simulator not initialized.",
        )

    command = request.command.lower().strip()
    before = simulator.get_all_joint_states()
    success = execute_command(simulator, command)

    if not success:
        return CommandResponse(
            success=False,
            message=f"Unknown command: {command}. Available: {list(COMMAND_MAP.keys())}",
        )

    if hardware_dispatcher is not None:
        after = simulator.get_all_joint_states()
        servo_cmds = []
        for joint, new_rad in after.items():
            if abs(new_rad - before.get(joint, 0.0)) > 1e-4:
                sid = SERVO_ID_MAP.get(joint)
                if sid is None:
                    continue
                servo_cmds.append(ServoCommand(
                    servo_id=sid,
                    position=rad_to_servo_units(new_rad),
                    duration_ms=400,
                ))
        if servo_cmds:
            await asyncio.to_thread(hardware_dispatcher.send_commands, servo_cmds)

    return CommandResponse(
        success=True,
        message=f"Executed command: {command}",
        joint_states=_get_robot_state(),
    )


@app.get("/commands")
async def list_commands() -> dict[str, list[str]]:
    """List all available commands."""
    return {"commands": list(COMMAND_MAP.keys())}


@app.get("/joint_states")
async def get_joint_states() -> dict[str, Any]:
    """Get current joint states."""
    global simulator

    return {"joint_states": _get_robot_state()}


@app.get("/primitives")
async def list_primitives() -> dict[str, Any]:
    """Return all primitives with metadata for testing UI.

    Returns parameterized primitive metadata including:
    - name, description, type (parameterized/composite/special)
    - default_angle, max_angle for slider controls
    - bidirectional flag and direction options
    - tags for filtering
    """
    return {"primitives": get_primitives_metadata()}


# ── Director-demo endpoints (simulation mode) ─────────────────────────────────
# These mirror the Pi robot_server.py contract (/motion, /state, /classify,
# /watch-for-action) so the frontend demo can run entirely on the Mac against the
# MuJoCo sim. Point the demo at this server with VITE_ROBOT_BASE=http://localhost:8000.
# /motion + /state drive the in-process sim here; /classify + /watch-for-action are
# proxied to the vision server (:8001), which owns the Mac webcam.
VISION_BASE = os.getenv("VISION_BASE", "http://localhost:8001")

# Demo motion name → sim command (COMMAND_MAP key). Names not found here fall
# through to execute_command directly (e.g. "wave"); unknown names are a no-op so
# pose-mimicry calls for unmapped classifier classes never break the demo.
DEMO_MOTION_ALIASES = {
    "stand": "reset",
    "reset": "reset",
}

_demo_state: str = "IDLE"
_pi_motions = None


class MotionRequest(BaseModel):
    name: str
    global_duration: float | None = None


class ServoMove(BaseModel):
    servo_id: int
    position: int
    duration_ms: int


class SetPoseRequest(BaseModel):
    """A raw pose as {joint_name: hardware_pulse}, e.g. pasted from motions.py."""
    pulses: dict[str, int]


class StateRequest(BaseModel):
    mode: str


def _get_pi_motions():
    """Lazily import the shared pose library (nodes/motions.py — pure data, no ROS)."""
    global _pi_motions
    if _pi_motions is None:
        from coral_agent.robot.pi.nodes import motions as pi_motions
        _pi_motions = pi_motions
    return _pi_motions


async def _play_sim_motion(name: str) -> bool:
    """Play a named pose/sequence from nodes/motions.py on the MuJoCo sim.

    Motion frames are hardware servo pulses (0–1000); convert each to sim radians
    with hardware_units_to_rad and set the joint targets, holding each frame for
    its duration so multi-frame motions (e.g. wave) animate. Returns False if the
    name is unknown so the caller can fall back to single-step commands.
    """
    sequence = _get_pi_motions().get_motion(name)
    if sequence is None or simulator is None:
        return False
    for pulse, duration_ms in sequence:
        for joint, units in pulse.items():
            try:
                simulator.set_joint_position(joint, hardware_units_to_rad(int(units), joint))
            except Exception as e:  # unknown joint / out-of-range — skip, keep going
                logger.debug(f"/motion: skip joint {joint}: {e}")
        await asyncio.sleep(max(0.0, float(duration_ms) / 1000.0))
    return True


@app.post("/motion")
async def demo_motion(req: MotionRequest) -> dict[str, Any]:
    """Run a named motion on the simulator (demo). Drives the sim from the shared
    nodes/motions.py pose library (wave, stand, and the 7 classifier poses), with
    a fall-back to single-step COMMAND_MAP primitives. Always 200 so an unmapped
    name never aborts the demo pipeline."""
    if simulator is None:
        return {"status": "error", "motion": req.name, "detail": "simulator not initialized"}
    name = req.name.strip()
    if await _play_sim_motion(name):
        return {"status": "done", "motion": name}
    # Fall back to single-step primitives (e.g. legacy COMMAND_MAP names).
    command = DEMO_MOTION_ALIASES.get(name.lower(), name.lower())
    if execute_command(simulator, command):
        return {"status": "done", "motion": name}
    logger.warning(f"/motion: no sim motion or command for '{name}' — skipped")
    return {"status": "skipped", "motion": name}


@app.get("/state")
async def demo_get_state() -> dict[str, str]:
    return {"state": _demo_state}


@app.post("/state")
async def demo_set_state(req: StateRequest) -> dict[str, str]:
    """Best-effort lock/unlock — the sim has no hard locks, so just record it."""
    global _demo_state
    _demo_state = req.mode
    return {"state": _demo_state}


@app.post("/classify")
async def demo_classify() -> dict[str, Any]:
    """Proxy to the vision server's real MobileNetV3 classifier (Mac webcam)."""
    try:
        # Generous timeout: the first call lazily loads the MobileNetV3 model.
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{VISION_BASE}/classify")
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=503, detail=f"vision server unreachable at {VISION_BASE}: {e}")


@app.post("/set-pose")
async def set_pose(req: SetPoseRequest) -> dict[str, Any]:
    """Apply a raw {joint: hardware_pulse} pose to the sim (testing tool).

    Accepts the exact pulse dicts authored in motions.py. Each pulse is a
    *hardware* servo unit, so it's converted to sim radians with
    hardware_units_to_rad (the same path /motion uses for named poses) — this
    is what makes joints whose hardware neutral isn't 500 (hip_pitch, ankles,
    sho_pitch, el_yaw) land at the right MuJoCo angle. set_joint_position then
    clamps each to its JOINT_LIMITS. Sim only; unknown joints are reported back.
    """
    if simulator is None:
        return {"status": "error", "detail": "simulator not initialized"}

    applied: list[str] = []
    skipped: list[str] = []
    for joint, pulse in req.pulses.items():
        if joint not in SERVO_ID_MAP:
            skipped.append(joint)
            continue
        try:
            simulator.set_joint_position(joint, hardware_units_to_rad(int(pulse), joint))
            applied.append(joint)
        except Exception as e:  # unknown sim joint / bad value — skip, keep going
            logger.debug(f"/set-pose: skip joint {joint}: {e}")
            skipped.append(joint)

    return {"status": "done", "applied": applied, "skipped": skipped}


@app.post("/move")
async def demo_move(moves: list[ServoMove]) -> dict[str, Any]:
    """Execute raw servo commands on the sim (and hardware, in robot mode).

    Used by the demo's pose-mimicry path: the frontend fetches servo commands
    from the vision server's /map-features (landmark retargeting) and posts them
    here to drive the robot. Mirrors the Pi robot_server's /move contract.
    """
    if simulator is None:
        return {"status": "error", "detail": "simulator not initialized"}
    commands = [
        ServoCommand(servo_id=m.servo_id, position=m.position, duration_ms=max(100, m.duration_ms))
        for m in moves
    ]
    await dispatch_servo_commands(commands)
    return {"status": "done", "count": len(commands)}


@app.get("/watch-for-action")
async def demo_watch_for_action(timeout: float = 30.0) -> dict[str, Any]:
    """Proxy to the vision server's hands-close gesture watcher (Mac webcam)."""
    try:
        async with httpx.AsyncClient(timeout=timeout + 5.0) as client:
            resp = await client.get(f"{VISION_BASE}/watch-for-action", params={"timeout": timeout})
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as e:
        # Don't break the demo's intro gate if vision is down — report "not detected".
        logger.warning(f"/watch-for-action proxy failed: {e}")
        return {"detected": False, "timeout": True}


class HierarchicalMemory:
    """Hierarchical memory management for chat context.

    Maintains:
    - Short-term: Last 3-5 exchanges (full detail)
    - Mid-term: Summarized task history
    - Action history: Structured log for Langfuse tracing and intent context
    """

    def __init__(self, short_term_limit: int = 6, mid_term_limit: int = 10):
        self.short_term: list[dict] = []
        self.mid_term_summaries: list[str] = []
        self.short_term_limit = short_term_limit
        self.mid_term_limit = mid_term_limit
        self.action_history: list[dict] = []

    def add_exchange(
        self, user_msg: str, assistant_msg: str, waypoints: list[dict]
    ) -> None:
        self.short_term.append({"role": "user", "content": user_msg})

        if waypoints:
            joints_summary = " | ".join(
                f"Joints set: {wp['joints']}" for wp in waypoints if wp.get("joints")
            )
            full_response = f"{assistant_msg} [{joints_summary}]" if joints_summary else assistant_msg
        else:
            full_response = assistant_msg

        self.short_term.append({"role": "assistant", "content": full_response})

        self.action_history.append({
            "user_request": user_msg,
            "waypoints": [
                {
                    "primitive": wp.get("primitive"),
                    "angle": wp.get("angle"),
                    "direction": wp.get("direction"),
                    "speed": wp.get("speed", 1.0),
                }
                for wp in waypoints
            ],
        })

        if len(self.short_term) > self.short_term_limit * 2:
            old_user = self.short_term.pop(0)["content"]
            self.short_term.pop(0)
            self.mid_term_summaries.append(f"User asked: {old_user[:50]}... Robot responded with motion.")
            if len(self.mid_term_summaries) > self.mid_term_limit:
                self.mid_term_summaries.pop(0)

    def get_context_for_llm(self) -> list[dict]:
        """Get formatted history for LLM context."""
        context = []

        # Add mid-term context summary if exists
        if self.mid_term_summaries:
            summary = "Previous interactions: " + " | ".join(
                self.mid_term_summaries[-5:]
            )
            context.append({"role": "system", "content": summary})

        # Add recent history
        context.extend(self.short_term)

        return context

    def get_structured_action_history(self) -> str:
        """Get structured action history for Langfuse tracing.

        Returns history in format:
        "1. 'user request' → [primitive direction angle° speed X, ...]"
        """
        if not self.action_history:
            return ""

        history_lines = []
        for i, seq in enumerate(self.action_history, 1):
            user_req = seq.get("user_request", "unknown")
            waypoints = seq.get("waypoints", [])
            if waypoints:
                wp_parts = []
                for wp in waypoints:
                    primitive = wp.get("primitive") or "direct_joints"
                    parts = [primitive]
                    if wp.get("direction"):
                        parts.append(wp["direction"])
                    if wp.get("angle") is not None:
                        parts.append(f"{wp['angle']}°")
                    if wp.get("speed") is not None:
                        parts.append(f"speed {wp['speed']}")
                    wp_parts.append(" ".join(parts))
                wp_summary = ", ".join(wp_parts)
                history_lines.append(f'{i}. "{user_req}" → [{wp_summary}]')
            else:
                history_lines.append(f'{i}. "{user_req}" → [no motion]')

        return "ACTION_HISTORY:\n" + "\n".join(history_lines)

    def get_last_n_action_sequences(self, n: int = 5) -> list[dict]:
        """Return the last N action sequences for the intent classifier."""
        return self.action_history[-n:] if self.action_history else []


def resolve_wp_entry(entry: dict) -> "Waypoint | None":
    """Resolve a single flat waypoint entry dict into a Waypoint."""
    primitive_names = entry.get("primitives", [])
    angle = entry.get("angle")
    direction = entry.get("direction")
    speed = entry.get("speed", 1.0)

    merged_joints: dict[str, float] = {}
    resolved_names: list[str] = []
    final_speed = speed
    resolved_angle = angle

    for primitive_name in primitive_names:
        result = resolve_primitive(primitive_name, angle=angle, direction=direction, speed=speed)
        if result:
            joints, prim_speed, resolved_name = result
            merged_joints.update(joints)
            resolved_names.append(resolved_name)
            final_speed = prim_speed
            if angle is None:
                prim_info = get_parameterized_primitive(resolved_name)
                resolved_angle = prim_info.default_angle if prim_info else None
            angle_info = f" angle={resolved_angle}°" if resolved_angle is not None else ""
            dir_info = f" direction={direction}" if direction else ""
            logger.info(f"Planner resolved primitive: {resolved_name}{angle_info}{dir_info}")
        else:
            prim = get_primitive(primitive_name)
            if prim:
                merged_joints.update(prim.joints)
                resolved_names.append(prim.name)
                logger.info(f"Planner resolved legacy primitive: {prim.name}")
            else:
                logger.warning(f"Planner hallucinated primitive: {primitive_name}")

    if not merged_joints:
        return None

    validation = validate_waypoint(merged_joints, clamp=True)
    wp = Waypoint(
        joints=validation.validated_joints,
        speed=final_speed,
        primitive_name=",".join(resolved_names),
        angle=resolved_angle,
        direction=direction,
    )
    wp.validation_result = validation
    logger.info(
        f"Built waypoint from [{', '.join(resolved_names)}] "
        f"with {len(merged_joints)} joints at speed {final_speed}"
    )
    return wp


async def _build_pre_context(
    simulator_instance: "AiNexSimulator | None",
    memory: "HierarchicalMemory",
) -> tuple[dict, str, list]:
    robot_state = await asyncio.to_thread(_get_robot_state)
    state_description = describe_joint_state(robot_state)
    memory_context = memory.get_context_for_llm()
    return robot_state, state_description, memory_context


@observe(name="process_chat_message")
async def process_chat_message(
    user_message: str,
    memory: "HierarchicalMemory",
    state_manager: "StateManager",
    recorder: "ConversationRecorder",
    simulator_instance: "AiNexSimulator | None",
    session_id: str,
    pre_context: tuple[dict, str, list] | None = None,
) -> dict:
    """Process a user message: single LLM call → primitive resolution → joint execution."""
    langfuse = get_client()

    with propagate_attributes(
        session_id=session_id,
        user_id="coral-user",
        tags=["coral-agent", "robot-control"],
    ):
        langfuse.update_current_span(input=user_message)

        if pre_context is not None:
            robot_state, state_description, memory_ctx = pre_context
        else:
            robot_state = _get_robot_state()
            state_description = describe_joint_state(robot_state)
            memory_ctx = memory.get_context_for_llm()

        contextual_message = (
            f"CURRENT_STATE: {json.dumps(convert_state_to_degrees(robot_state))}\n"
            f"STATE_DESCRIPTION: {state_description}\n\n"
            f"USER_REQUEST: {user_message}"
        )

        # --- SINGLE LLM CALL: Motion Planner ---
        @observe(name="motion_planner_llm")
        def run_motion_planner():
            prompt = get_router_prompt()
            messages = [
                {"role": "system", "content": prompt},
                *memory_ctx,
                {"role": "user", "content": contextual_message},
            ]
            llm_response = openai.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                response_format={"type": "json_object"},
                name="motion-planner",
            )
            cached = getattr(llm_response.usage.prompt_tokens_details, "cached_tokens", 0)
            logger.debug(f"LLM prompt tokens: {llm_response.usage.prompt_tokens} total, {cached} cached")
            return llm_response.choices[0].message.content

        planner_response_text = await asyncio.to_thread(run_motion_planner)
        plan_data = json.loads(planner_response_text)

        response = plan_data.get("verbal_response", "")

        # Each step is either a single Waypoint (sequential) or a list of parallel tracks.
        # A parallel track is itself a list[Waypoint] that executes concurrently with siblings.
        motion_steps: list[Waypoint | list[list[Waypoint]]] = []

        for entry in plan_data.get("waypoints", []):
            if "parallel" in entry:
                tracks: list[list[Waypoint]] = []
                for track_data in entry["parallel"]:
                    track_wps = [
                        wp
                        for raw in track_data.get("track", [])
                        if (wp := resolve_wp_entry(raw)) is not None
                    ]
                    if track_wps:
                        tracks.append(track_wps)
                if tracks:
                    motion_steps.append(tracks)
                    logger.info(f"Built parallel group with {len(tracks)} tracks")
            else:
                wp = resolve_wp_entry(entry)
                if wp:
                    motion_steps.append(wp)

        # Flatten all waypoints for validation and logging
        all_waypoints: list[Waypoint] = []
        for step in motion_steps:
            if isinstance(step, list):
                for track in step:
                    all_waypoints.extend(track)
            else:
                all_waypoints.append(step)

        executed_waypoints = []
        validation_warnings = []
        sign_warnings = []

        if motion_steps:
            if simulator_instance is not None:
                state_manager.save_checkpoint(
                    simulator_instance, f"before:{user_message[:30]}"
                )
            for wp in all_waypoints:
                if wp.validation_result and wp.validation_result.had_violations:
                    validation_warnings.extend(wp.validation_result.violations)
                motion_sign_issues = validate_motion_sign(user_message, wp.joints)
                if motion_sign_issues:
                    sign_warnings.extend(motion_sign_issues)
                    for warning in motion_sign_issues:
                        logger.warning(f"Sign validation: {warning}")

            # Execute motion steps: batch consecutive Waypoints together so
            # sequential movements run in one tight interpolation loop (matching
            # original behavior), while parallel groups are dispatched with gather.
            idx = 0
            while idx < len(motion_steps):
                step = motion_steps[idx]
                if isinstance(step, list):
                    result = await execute_parallel_tracks(simulator_instance, step)
                    executed_waypoints.extend(result)
                    idx += 1
                else:
                    batch: list[Waypoint] = []
                    while idx < len(motion_steps) and not isinstance(motion_steps[idx], list):
                        batch.append(motion_steps[idx])
                        idx += 1
                    result = await execute_waypoints(simulator_instance, batch)
                    executed_waypoints.extend(result)

        waypoints_data = [
            {
                "primitive": wp.primitive_name,
                "angle": wp.angle,
                "direction": wp.direction,
                "speed": wp.speed,
                "joints_radians": wp.joints,
                "joints_degrees": convert_state_to_degrees(wp.joints),
            }
            for wp in all_waypoints
        ]

        memory.add_exchange(user_message, response, waypoints_data)
        recorder.log_interaction(
            user_message=user_message,
            assistant_response=response,
            waypoints_extracted=waypoints_data,
            waypoints_executed=executed_waypoints,
            router_response=plan_data,
        )
        langfuse.update_current_span(
            output=response,
            metadata={
                "waypoints_count": len(all_waypoints),
                "action_history": memory.action_history,
            },
        )

        response_data = {
            "type": "chat_response",
            "role": "assistant",
            "content": response,
            "waypoints": executed_waypoints,
            "joint_states": _get_robot_state() or None,
        }

        if validation_warnings:
            response_data["validation_warnings"] = validation_warnings

        if sign_warnings:
            response_data["sign_warnings"] = sign_warnings

        return response_data


_FOLLOW_START_RE = re.compile(
    r"\b(follow|mimic|copy|mirror)\b.*\b(movement|movements|me|my\s+moves)\b",
    re.IGNORECASE,
)
_FOLLOW_STOP_RE = re.compile(
    r"\bstop\b(\s+(following|mimicking|copying|mirroring))?\b|\bquit\s+follow\b",
    re.IGNORECASE,
)
_CAPTURE_RE = re.compile(
    r"\b(capture|take|copy)\b.*\b(pose|position)\b",
    re.IGNORECASE,
)


def classify_system_intent(text: str, follow_active: bool) -> str | None:
    """Match voice/chat input to a follow/capture system action.

    Returns one of {"follow_start", "follow_stop", "capture_pose"} or None to
    fall through to the LLM motion planner.
    """
    t = text.strip()
    if not t:
        return None
    if _CAPTURE_RE.search(t):
        return "capture_pose"
    if _FOLLOW_START_RE.search(t):
        return "follow_start"
    if follow_active and _FOLLOW_STOP_RE.search(t):
        return "follow_stop"
    return None


async def _send_status(websocket: WebSocket, payload: dict) -> None:
    try:
        await websocket.send_json(payload)
    except Exception as e:
        logger.debug(f"Status send failed: {e}")


async def try_handle_system_intent(text: str, websocket: WebSocket) -> bool:
    """If the text matches a follow/capture intent, dispatch and reply. Return True if handled."""
    if follow_controller is None:
        return False

    intent = classify_system_intent(text, follow_active=follow_controller.is_following)
    if intent is None:
        return False

    async def status_fn(payload: dict) -> None:
        await _send_status(websocket, payload)

    if intent == "follow_start":
        await follow_controller.start_follow(status_fn)
        await websocket.send_json({
            "type": "chat_response",
            "role": "assistant",
            "content": "Following your movements — say stop when done.",
            "waypoints": [],
            "joint_states": _get_robot_state() or None,
        })
        return True

    if intent == "follow_stop":
        await follow_controller.stop_follow(status_fn)
        await websocket.send_json({
            "type": "chat_response",
            "role": "assistant",
            "content": "Stopped following.",
            "waypoints": [],
            "joint_states": _get_robot_state() or None,
        })
        return True

    if intent == "capture_pose":
        await follow_controller.trigger_capture_and_mimic(status_fn)
        await websocket.send_json({
            "type": "chat_response",
            "role": "assistant",
            "content": "Capturing your pose — hold still for a few seconds.",
            "waypoints": [],
            "joint_states": _get_robot_state() or None,
        })
        return True

    return False


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for chat and real-time updates."""
    global simulator

    await websocket.accept()
    connected_clients.add(websocket)
    logger.info(f"WebSocket client connected. Total clients: {len(connected_clients)}")

    # Initialize per-connection state
    memory = HierarchicalMemory()
    state_manager = StateManager(max_checkpoints=10)
    recorder = ConversationRecorder()
    session_id = f"ws-{id(websocket)}-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    # Save initial state as checkpoint
    if simulator:
        state_manager.save_checkpoint(simulator, "session_start")

    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            message_data = json.loads(data)

            msg_type = message_data.get("type", "chat")

            if msg_type == "command":
                command = message_data.get("command", "")
                success = False

                if command == "reset" and simulator is not None:
                    # Animate to stand pose through both sim and hardware instead of
                    # instantly teleporting the MuJoCo viewer.
                    stand = simulator.get_stand_joint_positions()
                    if stand:
                        state_manager.save_checkpoint(simulator, "before_command:reset")
                        cmds = []
                        for joint, rad in stand.items():
                            sid = SERVO_ID_MAP.get(joint)
                            if sid is not None:
                                cmds.append(ServoCommand(
                                    servo_id=sid,
                                    position=rad_to_servo_units(rad),
                                    duration_ms=1500,
                                ))
                        dispatches = []
                        if sim_dispatcher is not None:
                            dispatches.append(asyncio.to_thread(sim_dispatcher.send_commands, cmds))
                        if hardware_dispatcher is not None:
                            dispatches.append(asyncio.to_thread(hardware_dispatcher.send_commands, cmds))
                        if dispatches:
                            await asyncio.gather(*dispatches)
                        success = True

                elif command == "sync_sim":
                    # Instantly snap the sim viewer to the robot's current pose without
                    # sending any commands to the physical robot.  Useful when MuJoCo
                    # physics has tipped the sim over and you want it to mirror reality again.
                    if simulator is not None:
                        await asyncio.to_thread(_sync_sim_to_hardware)
                        success = True

                elif simulator is not None:
                    state_manager.save_checkpoint(simulator, f"before_command:{command}")
                    before = simulator.get_all_joint_states()
                    success = execute_command(simulator, command)
                    if success and hardware_dispatcher is not None:
                        after = simulator.get_all_joint_states()
                        servo_cmds = []
                        for joint, new_rad in after.items():
                            if abs(new_rad - before.get(joint, 0.0)) > 1e-4:
                                sid = SERVO_ID_MAP.get(joint)
                                if sid is None:
                                    continue
                                servo_cmds.append(ServoCommand(
                                    servo_id=sid,
                                    position=rad_to_servo_units(new_rad),
                                    duration_ms=400,
                                ))
                        if servo_cmds:
                            await asyncio.to_thread(hardware_dispatcher.send_commands, servo_cmds)

                await websocket.send_json({
                    "type": "command_result",
                    "success": success,
                    "command": command,
                    "joint_states": _get_robot_state() if success else None,
                })

            elif msg_type == "chat":
                # Chat message - process with full Langfuse tracing
                user_message = message_data.get("content", "")
                if await try_handle_system_intent(user_message, websocket):
                    continue
                response_data = await process_chat_message(
                    user_message=user_message,
                    memory=memory,
                    state_manager=state_manager,
                    recorder=recorder,
                    simulator_instance=simulator,
                    session_id=session_id,
                )
                await websocket.send_json(response_data)

            elif msg_type == "audio":
                audio_b64 = message_data.get("data", "")
                audio_bytes = base64.b64decode(audio_b64)
                transcribed_text, pre_context = await asyncio.gather(
                    asyncio.to_thread(transcribe_audio, audio_bytes),
                    _build_pre_context(simulator, memory),
                )
                await websocket.send_json({"type": "transcription", "text": transcribed_text})
                if transcribed_text.strip():
                    if await try_handle_system_intent(transcribed_text, websocket):
                        continue
                    response_data = await process_chat_message(
                        user_message=transcribed_text,
                        memory=memory,
                        state_manager=state_manager,
                        recorder=recorder,
                        simulator_instance=simulator,
                        session_id=session_id,
                        pre_context=pre_context,
                    )
                    await websocket.send_json(response_data)

            elif msg_type == "get_state":
                robot_state = await asyncio.to_thread(_get_robot_state)
                await websocket.send_json({
                    "type": "state",
                    "joint_states": robot_state,
                    "state_description": describe_joint_state(robot_state),
                    "checkpoint_count": state_manager.checkpoint_count,
                    "running": simulator.is_running() if simulator is not None else True,
                })

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        import traceback

        traceback.print_exc()
        try:
            await websocket.send_json({
                "type": "chat_response",
                "role": "assistant",
                "content": "Sorry, an error occurred processing your request.",
                "waypoints": [],
                "joint_states": _get_robot_state() or None,
            })
        except Exception:
            pass
    finally:
        connected_clients.discard(websocket)
        if follow_controller is not None and follow_controller.is_following:
            await follow_controller.stop_follow()
        logger.info(
            f"WebSocket client removed. Total clients: {len(connected_clients)}"
        )


def _reexec_under_mjpython_if_needed() -> None:
    """Re-exec under `mjpython` on macOS so the MuJoCo viewer window can open.

    MuJoCo's interactive viewer (`launch_passive`) raises on macOS unless the
    process is launched via `mjpython`, which keeps the Cocoa UI loop on the real
    main thread while running Python on a worker thread. Under plain `python` /
    `uv run` the viewer thread dies with:
        RuntimeError: `launch_passive` requires ... `mjpython` on macOS
    and no window appears (the server itself keeps running). Re-exec the current
    entry point under mjpython so `uv run server` / `uv run robot` show the robot.

    No-op off macOS, once already re-exec'd, or when CORAL_NO_VIEWER=1 — set that
    for headless/CI runs that should stay on plain python (no window).
    """
    if sys.platform != "darwin":
        return
    if os.environ.get("CORAL_MJPYTHON") == "1" or os.environ.get("CORAL_NO_VIEWER") == "1":
        return
    mjpython = Path(sys.executable).with_name("mjpython")
    if not mjpython.exists():
        logger.warning(
            "mjpython not found next to the interpreter; the MuJoCo viewer window "
            "won't open on macOS. Set CORAL_NO_VIEWER=1 to silence this."
        )
        return
    # Forward the current entry script + args so the same console entry (server vs
    # robot) re-runs under mjpython. CORAL_MJPYTHON guards against a re-exec loop.
    argv = sys.argv if sys.argv and Path(sys.argv[0]).exists() else ["-m", "coral_agent.server"]
    os.environ["CORAL_MJPYTHON"] = "1"
    logger.info("macOS: re-launching under mjpython so the MuJoCo viewer window opens...")
    os.execv(str(mjpython), [str(mjpython), *argv])


def main():
    """Entry point for simulation mode (default — starts MuJoCo)."""
    _reexec_under_mjpython_if_needed()
    logger.info("Starting Coral AI Agent server (sim mode)...")
    uvicorn.run(
        "coral_agent.server:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )


def main_robot():
    """Entry point for hardware robot mode — no MuJoCo, commands sent to physical robot.

    Requires:
      - ROBOT_IP env var set to the robot's IP (default: 192.168.8.219)
      - robot_server.py running on the robot (uv run robot-server)
      - Laptop on the same network as the robot
    """
    _reexec_under_mjpython_if_needed()
    os.environ.setdefault("ROBOT_MODE", "robot")
    robot_ip = os.getenv("ROBOT_IP", "192.168.8.219")
    logger.info(f"Starting Coral AI Agent server in ROBOT mode (target: {robot_ip})")
    logger.info("Frontend: run 'npm run dev' in the frontend/ directory")
    logger.info(f"Make sure robot_server.py is running on the robot at {robot_ip}:9000")
    uvicorn.run(
        "coral_agent.server:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )


def main_sim_test():
    """Entry point for sim test mode — cycle the sim robot through every pose in motions.py.

    Launches only the MuJoCo simulator (no server, no LLM, no hardware) and walks
    the robot through each motion in ``motions.MOTIONS`` sequentially, resetting to
    stand between motions, looping until the viewer window is closed or Ctrl+C.

    Usage:
        uv run sim-test              # cycle through all motions
        uv run sim-test dab wave     # only these motions
    """
    import time

    from coral_agent.robot.motions import MOTIONS

    _reexec_under_mjpython_if_needed()

    hold_seconds = float(os.getenv("SIM_TEST_HOLD_SECONDS", "2.0"))

    requested = [a for a in sys.argv[1:] if not a.startswith("-")]
    names = requested or list(MOTIONS.keys())
    unknown = [n for n in names if n not in MOTIONS]
    if unknown:
        logger.error(f"Unknown motion(s): {unknown}. Available: {list(MOTIONS.keys())}")
        return

    logger.info("Starting AiNex MuJoCo simulator (sim test mode)...")
    sim = AiNexSimulator()
    sim.start_viewer()
    time.sleep(1.0)  # let the viewer window come up

    logger.info(f"Cycling through {len(names)} motion(s): {names}")
    try:
        while sim.is_running():
            for name in names:
                if not sim.is_running():
                    break
                motion = MOTIONS[name]
                logger.info(f"=== Motion: {name} ({len(motion)} frame(s)) ===")
                for pulse, duration_ms in motion:
                    # Motion frames are hardware servo pulses (STAND_PULSE = per-joint
                    # neutral). Convert with hardware_units_to_rad — anchored to the sim's
                    # stand keyframe — so joints held at their stand pulse stay put. The
                    # naive servo_units_to_rad (500 = 0 rad for every joint) would move the
                    # bent-knee legs and tip the robot even on stand-identical poses.
                    #
                    # Ramp each joint from its current target to the frame target across
                    # duration_ms in ~20ms steps, so duration_ms sets the actual move
                    # speed. Setting the target instantly makes the PD controller snap
                    # the legs and topple the robot.
                    ramps = []
                    for joint, units in pulse.items():
                        try:
                            start = sim.get_joint_position(joint)
                            target = hardware_units_to_rad(int(units), joint)
                        except Exception as e:  # unknown joint — skip, keep going
                            logger.debug(f"sim-test: skip joint {joint}: {e}")
                            continue
                        ramps.append((joint, start, target))
                    steps = max(1, int(duration_ms) // 20)
                    for i in range(1, steps + 1):
                        frac = i / steps
                        for joint, start, target in ramps:
                            sim.set_joint_position(joint, start + frac * (target - start))
                        time.sleep(0.02)
                time.sleep(hold_seconds)
                logger.info("  resetting to stand")
                sim.reset_pose()
                time.sleep(hold_seconds)
    except KeyboardInterrupt:
        logger.info("Interrupted — stopping sim test.")
    finally:
        sim.stop_viewer()


if __name__ == "__main__":
    main()
