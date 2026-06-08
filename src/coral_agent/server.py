"""FastAPI server for the Coral AI agent with MuJoCo simulation."""

import asyncio
import base64
import json
import math
import os
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
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pydantic import BaseModel

from coral_agent.config import LLM_MODEL
from coral_agent.gesture_library import (
    GESTURE_LIBRARY,
    get_gesture as get_library_gesture,
)
from coral_agent.primitives import (
    get_parameterized_primitive,
    get_primitive,
    get_primitives_metadata,
    resolve_primitive,
)


def convert_state_to_degrees(state: dict[str, float]) -> dict[str, float]:
    return {joint: round(math.degrees(value), 1) for joint, value in state.items()}


from coral_agent.simulator import ApolloSimulator
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

# Global simulator instance
simulator: ApolloSimulator | None = None


_router_prompt_cache: str | None = None


def get_router_prompt() -> str:
    global _router_prompt_cache
    if _router_prompt_cache is None:
        _router_prompt_cache = (Path(__file__).parent / "prompts" / "router.md").read_text(encoding="utf-8")
    return _router_prompt_cache


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan - start/stop simulator and Langfuse."""
    global simulator

    logger.info("Starting Apollo simulator...")
    simulator = ApolloSimulator()
    simulator.start_viewer()

    # Initialize Langfuse client for shutdown flush
    langfuse_client = Langfuse()
    logger.info("Langfuse tracing initialized")

    yield

    logger.info("Stopping Apollo simulator...")
    if simulator:
        simulator.stop_viewer()

    # Flush pending Langfuse traces before shutdown
    logger.info("Flushing Langfuse traces...")
    langfuse_client.flush()


app = FastAPI(title="Coral AI Agent", lifespan=lifespan)

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
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
        segments, _ = model.transcribe(tmp_path, language="en")
        return " ".join(seg.text.strip() for seg in segments).strip()
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




async def execute_waypoints(
    simulator: ApolloSimulator, waypoints: list[Waypoint]
) -> list[dict]:
    """Execute a sequence of waypoints with interpolation.

    Each waypoint is reached by interpolating from current position to target.
    Speed determines how fast the interpolation happens (higher = faster).

    Returns a list of executed waypoint info.
    """
    executed = []
    base_steps = 20  # Base number of interpolation steps at speod=1.0
    step_delay = 0.02  # Delay between interpolation steps (seconds)

    for i, waypoint in enumerate(waypoints):
        # Calculate number of steps based on speed (faster = fewer steps)
        num_steps = max(5, int(base_steps / waypoint.speed))

        # Get current positions for joints we're going to move
        current_positions = {}
        for joint_name in waypoint.joints:
            try:
                current_positions[joint_name] = simulator.get_joint_position(joint_name)
            except ValueError:
                logger.warning(f"Unknown joint in waypoint: {joint_name}")
                continue

        # Interpolate from current to target
        for step in range(1, num_steps + 1):
            t = step / num_steps  # Progress from 0 to 1

            for joint_name, target_pos in waypoint.joints.items():
                if joint_name not in current_positions:
                    continue

                current = current_positions[joint_name]
                # Linear interpolation
                interpolated = current + (target_pos - current) * t
                simulator.set_joint_position(joint_name, interpolated)

            # Small delay for smooth animation
            await asyncio.sleep(step_delay)

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
            f"angle={waypoint.angle} speed={waypoint.speed}"
        )

    return executed


@app.post("/command", response_model=CommandResponse)
async def execute_manual_command(request: CommandRequest) -> CommandResponse:
    """Execute a manual robot command."""
    global simulator

    if simulator is None:
        return CommandResponse(success=False, message="Simulator not initialized")

    command = request.command.lower().strip()
    success = execute_command(simulator, command)

    if success:
        joint_states = simulator.get_all_joint_states()
        return CommandResponse(
            success=True,
            message=f"Executed command: {command}",
            joint_states=joint_states,
        )
    else:
        return CommandResponse(
            success=False,
            message=f"Unknown command: {command}. Available: {list(COMMAND_MAP.keys())}",
        )


@app.get("/commands")
async def list_commands() -> dict[str, list[str]]:
    """List all available commands."""
    return {"commands": list(COMMAND_MAP.keys())}


@app.get("/joint_states")
async def get_joint_states() -> dict[str, Any]:
    """Get current joint states."""
    global simulator

    if simulator is None:
        return {"error": "Simulator not initialized"}

    return {"joint_states": simulator.get_all_joint_states()}


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


@app.get("/gestures")
async def list_gestures() -> dict[str, Any]:
    """Return all gestures from the gesture library."""
    gestures_list = [
        {
            "name": g.name,
            "description": g.description,
            "category": g.category,
            "keyframe_count": len(g.keyframes),
            "total_duration": sum(g.durations),
            "tags": g.tags,
        }
        for g in GESTURE_LIBRARY.values()
    ]
    return {"gestures": gestures_list}


class TestPrimitiveRequest(BaseModel):
    """Request body for testing primitives with parameters."""

    angle: float | None = None
    direction: str | None = None
    speed: float | None = None


@app.post("/test-primitive/{name}")
async def test_primitive(name: str, request: TestPrimitiveRequest | None = None) -> dict[str, Any]:
    """Execute a primitive directly for testing.

    Supports parameterized primitives with optional angle, direction, and speed.

    Args:
        name: Primitive name (e.g., 'left_arm_out', 'head_turn')
        request: Optional parameters:
            - angle: Angle in degrees (0-180)
            - direction: 'left', 'right', 'up', 'down' for bidirectional primitives
            - speed: Speed multiplier (0.1-5.0)
    """
    global simulator

    if simulator is None:
        return {"success": False, "error": "Simulator not initialized"}

    # Extract parameters from request body
    angle = request.angle if request else None
    direction = request.direction if request else None
    speed = request.speed if request else None

    # Try to resolve as a parameterized primitive first
    result = resolve_primitive(name, angle=angle, direction=direction, speed=speed)

    if result:
        joints, final_speed, resolved_name = result
        # Validate and execute with interpolation
        validation = validate_waypoint(joints, clamp=True)
        wp = Waypoint(
            joints=validation.validated_joints,
            speed=final_speed,
            primitive_name=resolved_name,
        )

        await execute_waypoints(simulator, [wp])

        # Get primitive metadata for response
        prim = get_parameterized_primitive(resolved_name)
        description = prim.description if prim else resolved_name
        bidirectional = prim.bidirectional if prim else False
        max_angle = prim.max_angle if prim else 180

        return {
            "success": True,
            "primitive": resolved_name,
            "description": description,
            "joints": joints,
            "angle": angle,
            "direction": direction,
            "speed": final_speed,
            "bidirectional": bidirectional,
            "max_angle": max_angle,
            "is_gesture": False,
            "joint_states": simulator.get_all_joint_states(),
        }

    # Fall back to legacy get_primitive for old-style lookups
    primitive = get_primitive(name)
    if not primitive:
        return {"success": False, "error": f"Unknown primitive: {name}"}

    # Validate and execute with interpolation
    validation = validate_waypoint(primitive.joints, clamp=True)
    wp = Waypoint(
        joints=validation.validated_joints,
        speed=speed or primitive.speed,
        primitive_name=primitive.name,
    )

    await execute_waypoints(simulator, [wp])

    return {
        "success": True,
        "primitive": primitive.name,
        "description": primitive.description,
        "joints": primitive.joints,
        "is_gesture": False,
        "joint_states": simulator.get_all_joint_states(),
    }


@app.post("/test-gesture/{name}")
async def test_gesture(name: str) -> dict[str, Any]:
    """Execute a gesture (animated sequence) for testing."""
    global simulator

    if simulator is None:
        return {"success": False, "error": "Simulator not initialized"}

    gesture = get_library_gesture(name)
    if not gesture:
        return {"success": False, "error": f"Unknown gesture: {name}"}

    # Execute gesture as sequence of waypoints with timing
    for i, keyframe in enumerate(gesture.keyframes):
        validation = validate_waypoint(keyframe, clamp=True)

        # Calculate speed from duration (shorter duration = faster speed)
        duration = gesture.durations[i] if i < len(gesture.durations) else 0.5
        # Base interpolation takes ~0.4s at speed=1.0, adjust accordingly
        speed = 0.4 / duration if duration > 0 else 1.0
        speed = max(0.5, min(speed, 8.0))  # Allow up to 8x speed for fast gestures

        wp = Waypoint(
            joints=validation.validated_joints,
            speed=speed,
            primitive_name=f"{gesture.name}_frame{i+1}",
        )

        await execute_waypoints(simulator, [wp])

    return {
        "success": True,
        "gesture": gesture.name,
        "description": gesture.description,
        "category": gesture.category,
        "keyframe_count": len(gesture.keyframes),
        "total_duration": sum(gesture.durations),
        "joint_states": simulator.get_all_joint_states(),
    }


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


@observe(name="process_chat_message")
async def process_chat_message(
    user_message: str,
    memory: "HierarchicalMemory",
    state_manager: "StateManager",
    recorder: "ConversationRecorder",
    simulator_instance: "ApolloSimulator | None",
    session_id: str,
) -> dict:
    """Process a user message: single LLM call → primitive resolution → joint execution."""
    langfuse = get_client()

    with propagate_attributes(
        session_id=session_id,
        user_id="coral-user",
        tags=["coral-agent", "robot-control"],
    ):
        langfuse.update_current_span(input=user_message)

        robot_state = simulator_instance.get_all_joint_states() if simulator_instance else {}
        state_description = describe_joint_state(robot_state)

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
                {"role": "user", "content": contextual_message},
            ]
            llm_response = openai.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                response_format={"type": "json_object"},
                name="motion-planner",
            )
            return llm_response.choices[0].message.content

        planner_response_text = await asyncio.to_thread(run_motion_planner)
        plan_data = json.loads(planner_response_text)

        response = ""

        waypoints = []
        for wp_entry in plan_data.get("waypoints", []):
            primitive_names = wp_entry.get("primitives", [])
            angle = wp_entry.get("angle")
            direction = wp_entry.get("direction")
            speed = wp_entry.get("speed", 1.0)

            # Resolve and merge all primitives in this entry into one simultaneous move
            merged_joints: dict[str, float] = {}
            resolved_names: list[str] = []
            final_speed = speed

            for primitive_name in primitive_names:
                result = resolve_primitive(
                    primitive_name,
                    angle=angle,
                    direction=direction,
                    speed=speed,
                )
                if result:
                    joints, prim_speed, resolved_name = result
                    merged_joints.update(joints)
                    resolved_names.append(resolved_name)
                    final_speed = prim_speed
                    angle_info = f" angle={angle}°" if angle else ""
                    dir_info = f" direction={direction}" if direction else ""
                    logger.info(
                        f"Planner resolved primitive: {resolved_name}{angle_info}{dir_info}"
                    )
                else:
                    # Fall back to legacy get_primitive
                    prim = get_primitive(primitive_name)
                    if prim:
                        merged_joints.update(prim.joints)
                        resolved_names.append(prim.name)
                        logger.info(f"Planner resolved legacy primitive: {prim.name}")
                    else:
                        logger.warning(f"Planner hallucinated primitive: {primitive_name}")

            if merged_joints:
                validation = validate_waypoint(merged_joints, clamp=True)
                wp = Waypoint(
                    joints=validation.validated_joints,
                    speed=final_speed,
                    primitive_name=",".join(resolved_names),
                    angle=angle,
                    direction=direction,
                )
                wp.validation_result = validation
                waypoints.append(wp)
                logger.info(
                    f"Built waypoint from [{', '.join(resolved_names)}] "
                    f"with {len(merged_joints)} joints at speed {final_speed}"
                )

        executed_waypoints = []
        validation_warnings = []
        sign_warnings = []

        if simulator_instance and waypoints:
            state_manager.save_checkpoint(
                simulator_instance, f"before:{user_message[:30]}"
            )
            for wp in waypoints:
                if wp.validation_result and wp.validation_result.had_violations:
                    validation_warnings.extend(wp.validation_result.violations)
                motion_sign_issues = validate_motion_sign(user_message, wp.joints)
                if motion_sign_issues:
                    sign_warnings.extend(motion_sign_issues)
                    for warning in motion_sign_issues:
                        logger.warning(f"Sign validation: {warning}")
            executed_waypoints = await execute_waypoints(simulator_instance, waypoints)

        waypoints_data = [
            {
                "primitive": wp.primitive_name,
                "angle": wp.angle,
                "direction": wp.direction,
                "speed": wp.speed,
                "joints_radians": wp.joints,
                "joints_degrees": convert_state_to_degrees(wp.joints),
            }
            for wp in waypoints
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
                "waypoints_count": len(waypoints),
                "action_history": memory.action_history,
            },
        )

        response_data = {
            "type": "chat_response",
            "role": "assistant",
            "content": response,
            "waypoints": executed_waypoints,
            "joint_states": (
                simulator_instance.get_all_joint_states() if simulator_instance else None
            ),
        }

        if validation_warnings:
            response_data["validation_warnings"] = validation_warnings

        if sign_warnings:
            response_data["sign_warnings"] = sign_warnings

        return response_data


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
                # Direct command execution
                command = message_data.get("command", "")
                if simulator:
                    # Save checkpoint before command
                    state_manager.save_checkpoint(
                        simulator, f"before_command:{command}"
                    )
                    success = execute_command(simulator, command)
                    await websocket.send_json(
                        {
                            "type": "command_result",
                            "success": success,
                            "command": command,
                            "joint_states": (
                                simulator.get_all_joint_states() if success else None
                            ),
                        }
                    )

            elif msg_type == "chat":
                # Chat message - process with full Langfuse tracing
                user_message = message_data.get("content", "")
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
                transcribed_text = await asyncio.to_thread(transcribe_audio, audio_bytes)
                await websocket.send_json({"type": "transcription", "text": transcribed_text})
                if transcribed_text.strip():
                    response_data = await process_chat_message(
                        user_message=transcribed_text,
                        memory=memory,
                        state_manager=state_manager,
                        recorder=recorder,
                        simulator_instance=simulator,
                        session_id=session_id,
                    )
                    await websocket.send_json(response_data)

            elif msg_type == "get_state":
                # Request current robot state
                if simulator:
                    robot_state = simulator.get_all_joint_states()
                    await websocket.send_json(
                        {
                            "type": "state",
                            "joint_states": robot_state,
                            "state_description": describe_joint_state(robot_state),
                            "checkpoint_count": state_manager.checkpoint_count,
                            "running": simulator.is_running(),
                        }
                    )

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        import traceback

        traceback.print_exc()
    finally:
        connected_clients.discard(websocket)
        logger.info(
            f"WebSocket client removed. Total clients: {len(connected_clients)}"
        )


def main():
    """Main entry point for the server."""
    logger.info("Starting Coral AI Agent server...")
    uvicorn.run(
        "coral_agent.server:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
