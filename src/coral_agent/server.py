"""FastAPI server for the Coral AI agent with MuJoCo simulation."""

import asyncio
import json
import re
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import ollama
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pydantic import BaseModel

from coral_agent.intent import (
    IntentResult,
    IntentType,
    build_correction_context,
    build_retry_context,
    classify_intent,
    quick_intent_check,
)
from coral_agent.primitives import (
    PRIMITIVES,
    detect_degrees_in_request,
    detect_plural_arms,
    get_primitive,
    get_primitives_list,
)
from coral_agent.schemas import LLMResponse, WaypointOutput
from coral_agent.simulator import ApolloSimulator
from coral_agent.simulator.mujoco_sim import COMMAND_MAP, execute_command
from coral_agent.state import (
    RollbackIntent,
    StateManager,
    execute_rollback,
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


def get_router_prompt() -> str:
    prompt_path = Path(__file__).parent / "prompts" / "router.md"
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()


def get_kinematics_prompt() -> str:
    prompt_path = Path(__file__).parent / "prompts" / "kinematics.md"
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan - start/stop simulator."""
    global simulator

    logger.info("Starting Apollo simulator...")
    simulator = ApolloSimulator()
    simulator.start_viewer()

    yield

    logger.info("Stopping Apollo simulator...")
    if simulator:
        simulator.stop_viewer()


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
    ) -> None:
        """Log a single interaction (user message + assistant response)."""
        interaction = {
            "timestamp": datetime.now().isoformat(),
            "user": user_message,
            "assistant": assistant_response,
            "waypoints_extracted": waypoints_extracted,
            "waypoints_executed": waypoints_executed,
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
    """A single waypoint with target joint positions and speed."""

    def __init__(
        self,
        joints: dict[str, float],
        speed: float = 1.0,
        reasoning: str = "",
        primitive_name: str | None = None,
    ):
        self.joints = joints  # {"joint_name": target_position}
        self.speed = max(0.1, min(speed, 5.0))  # Clamp speed between 0.1 and 5.0
        self.reasoning = reasoning
        self.primitive_name = primitive_name
        self.validation_result: ValidationResult | None = None


def normalize_waypoint_joints(raw_joints: dict) -> dict[str, float]:
    """Normalize waypoint joints to {joint_name: value} format.

    Handles two formats:
    1. Correct: {"neck_yaw": 0.7, "neck_pitch": 0.3}
    2. LLM mistake: {"joint_name": "neck_yaw", "value": 0.7}
    """
    # Check if this is the incorrect format with "joint_name" and "value" keys
    if "joint_name" in raw_joints and "value" in raw_joints:
        joint_name = raw_joints["joint_name"]
        value = raw_joints["value"]
        if isinstance(joint_name, str) and isinstance(value, (int, float)):
            return {joint_name: float(value)}
        else:
            logger.warning(f"Invalid joint_name/value types: {raw_joints}")
            return {}

    # Otherwise assume correct format - filter to only numeric values
    normalized = {}
    for key, val in raw_joints.items():
        if key == "speed":
            continue  # Skip speed if it was included in the joints object
        if isinstance(val, (int, float)):
            normalized[key] = float(val)
        else:
            logger.warning(f"Skipping non-numeric joint value: {key}={val}")

    return normalized


def extract_waypoints(text: str) -> list[Waypoint]:
    """Extract waypoints from LLM response text.

    Supports multiple formats:
    1. New structured JSON: {"thought_process": ..., "waypoints": [...], "verbal_response": ...}
    2. Legacy format: [WAYPOINT: {"joint": value, ...}, speed]
    """
    waypoints = []

    # First, try to parse as structured JSON response
    structured_waypoints = extract_structured_waypoints(text)
    if structured_waypoints:
        return structured_waypoints

    # Fall back to legacy [WAYPOINT: ...] format
    pattern = r"\[WAYPOINT:\s*(\{[^}]+\})(?:\s*,\s*(\d+(?:\.\d+)?))?\s*\]"
    matches = re.findall(pattern, text, re.IGNORECASE)

    for joints_str, speed_str in matches:
        try:
            raw_joints = json.loads(joints_str)
            joints = normalize_waypoint_joints(raw_joints)

            if not joints:
                logger.warning(f"No valid joints extracted from: {joints_str}")
                continue

            speed = float(speed_str) if speed_str else 1.0

            # Validate and clamp joint values
            validation = validate_waypoint(joints, clamp=True)
            if validation.had_violations:
                for violation in validation.violations:
                    logger.warning(f"Joint limit violation: {violation}")

            wp = Waypoint(joints=validation.validated_joints, speed=speed)
            wp.validation_result = validation
            waypoints.append(wp)
            logger.info(
                f"Extracted waypoint: joints={validation.validated_joints}, speed={speed}"
            )
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse waypoint JSON: {joints_str}, error: {e}")
        except Exception as e:
            logger.warning(f"Failed to process waypoint: {e}")

    return waypoints


def extract_structured_waypoints(text: str) -> list[Waypoint] | None:
    """Try to extract waypoints from structured JSON format.

    Returns None if no structured format found.
    """
    # Look for JSON block in the response
    json_pattern = r"```json\s*(.*?)\s*```"
    json_match = re.search(json_pattern, text, re.DOTALL)

    if json_match:
        json_str = json_match.group(1)
    else:
        # Try to find raw JSON object
        try:
            # Look for object that starts with { and has thought_process
            start = text.find('{"thought_process"')
            if start == -1:
                start = text.find('{\n  "thought_process"')
            if start == -1:
                return None

            # Find matching closing brace
            depth = 0
            end = start
            for i, char in enumerate(text[start:]):
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        end = start + i + 1
                        break
            json_str = text[start:end]
        except Exception:
            return None

    try:
        data = json.loads(json_str)
        response = LLMResponse(**data)
        waypoints = []

        for wp_data in response.waypoints:
            if wp_data.primitive:
                # Resolve primitive to joints (with fuzzy matching)
                prim = get_primitive(wp_data.primitive)
                if prim:
                    joints = prim.joints.copy()
                    validation = validate_waypoint(joints, clamp=True)
                    wp = Waypoint(
                        joints=validation.validated_joints,
                        speed=wp_data.speed,
                        reasoning=wp_data.reasoning,
                        primitive_name=prim.name,  # Use resolved name
                    )
                    wp.validation_result = validation
                    waypoints.append(wp)
                    if prim.name != wp_data.primitive.lower().replace(" ", "_"):
                        logger.info(
                            f"Fuzzy matched '{wp_data.primitive}' -> '{prim.name}'"
                        )
                    logger.info(
                        f"Resolved primitive '{prim.name}' to {len(joints)} joints: {list(joints.keys())}"
                    )
                else:
                    logger.warning(
                        f"Unknown primitive '{wp_data.primitive}' - no match found. Available: {list(PRIMITIVES.keys())}"
                    )
            elif wp_data.joints:
                validation = validate_waypoint(wp_data.joints, clamp=True)
                if validation.had_violations:
                    for violation in validation.violations:
                        logger.warning(f"Joint limit violation: {violation}")

                wp = Waypoint(
                    joints=validation.validated_joints,
                    speed=wp_data.speed,
                    reasoning=wp_data.reasoning,
                )
                wp.validation_result = validation
                waypoints.append(wp)

        logger.info(f"Extracted {len(waypoints)} waypoints from structured response")
        return waypoints if waypoints else None

    except json.JSONDecodeError as e:
        logger.debug(f"Failed to parse structured JSON: {e}")
        return None
    except Exception as e:
        logger.debug(f"Failed to process structured response: {e}")
        return None


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
                "joints": waypoint.joints,
                "speed": waypoint.speed,
            }
        )
        logger.info(
            f"Executed waypoint {i}: {waypoint.joints} at speed {waypoint.speed}"
        )

    return executed


def build_system_prompt() -> str:
    """Build the system prompt by loading main.md and injecting primitives."""
    primitives_list = get_primitives_list()

    # Path to the prompts directory relative to server.py
    prompt_path = Path(__file__).parent / "prompts" / "main.md"

    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            prompt_template = f.read()

        # Inject the primitives list using replace to avoid JSON bracket clashes
        final_prompt = prompt_template.replace("{primitives_list}", primitives_list)
        return final_prompt

    except FileNotFoundError:
        logger.error(f"Prompt file not found at {prompt_path}")
        # Fallback to a minimal prompt if the file is missing
        return "You are a robot controller. Output valid JSON."


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


class HierarchicalMemory:
    """Hierarchical memory management for chat context.

    Maintains:
    - Short-term: Last 3-5 exchanges (full detail)
    - Mid-term: Summarized task history
    - Last executed: Most recent waypoints for modification
    - Last user request: For retry/correction context
    """

    def __init__(self, short_term_limit: int = 6, mid_term_limit: int = 10):
        self.short_term: list[dict] = []
        self.mid_term_summaries: list[str] = []
        self.last_executed_waypoints: list[dict] = []
        self.last_user_request: str | None = None
        self.last_action_summary: str | None = None
        self.short_term_limit = short_term_limit
        self.mid_term_limit = mid_term_limit

    def add_exchange(
        self, user_msg: str, assistant_msg: str, waypoints: list[dict]
    ) -> None:
        """Add a conversation exchange."""
        self.short_term.append({"role": "user", "content": user_msg})
        self.short_term.append({"role": "assistant", "content": assistant_msg})
        self.last_executed_waypoints = waypoints
        self.last_user_request = user_msg

        # Build action summary for intent classifier
        if waypoints:
            joint_names = []
            for wp in waypoints:
                joint_names.extend(wp.get("joints", {}).keys())
            self.last_action_summary = f"Moved joints: {', '.join(set(joint_names))}"
        else:
            self.last_action_summary = "No motion executed"

        # Roll over to mid-term if needed
        if len(self.short_term) > self.short_term_limit * 2:
            # Summarize oldest exchanges
            old_user = self.short_term.pop(0)["content"]
            old_assistant = self.short_term.pop(0)["content"]
            summary = f"User asked: {old_user[:50]}... Robot responded with motion."
            self.mid_term_summaries.append(summary)

            # Keep mid-term bounded
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

    def get_last_waypoints_summary(self) -> str:
        """Get summary of last executed waypoints for modification requests."""
        if not self.last_executed_waypoints:
            return "No recent waypoints executed."

        summaries = []
        for wp in self.last_executed_waypoints:
            joints = wp.get("joints", {})
            speed = wp.get("speed", 1.0)
            primitive = wp.get("primitive")
            if primitive:
                summaries.append(f"Used primitive '{primitive}' at speed {speed}")
            else:
                summaries.append(
                    f"Moved {list(joints.keys())} to {list(joints.values())} at speed {speed}"
                )

        return "Last executed: " + "; ".join(summaries)


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
                # Chat message - use two-stage LLM architecture
                user_message = message_data.get("content", "")

                # === STAGE 1: Intent Classification ===
                # First try fast-path keyword detection
                has_previous = memory.last_user_request is not None
                intent = quick_intent_check(user_message, has_previous)

                if intent:
                    logger.info(
                        f"Fast-path intent: {intent.intent_type.value} ({intent.confidence:.2f})"
                    )
                else:
                    # Fall back to LLM classification
                    intent = await asyncio.to_thread(
                        classify_intent,
                        user_message,
                        memory.last_user_request,
                        memory.last_action_summary,
                    )
                    logger.info(
                        f"LLM intent: {intent.intent_type.value} ({intent.confidence:.2f})"
                    )

                # Handle based on intent type
                if intent.intent_type == IntentType.UNDO and simulator:
                    # Simple undo - rollback without retry
                    rollback_intent = RollbackIntent(
                        command_type="undo", steps=1, confidence=intent.confidence
                    )
                    result = await execute_rollback(
                        simulator, state_manager, rollback_intent
                    )
                    response = (
                        "Done! Rolled back to previous state."
                        if result
                        else "No previous state to go back to."
                    )
                    await websocket.send_json(
                        {
                            "type": "chat_response",
                            "role": "assistant",
                            "content": response,
                            "waypoints": [],
                            "intent": intent.intent_type.value,
                            "joint_states": simulator.get_all_joint_states(),
                        }
                    )
                    continue

                if intent.intent_type == IntentType.RESET and simulator:
                    # Reset to initial position
                    rollback_intent = RollbackIntent(
                        command_type="reset", steps=-1, confidence=intent.confidence
                    )
                    result = await execute_rollback(
                        simulator, state_manager, rollback_intent
                    )
                    response = "Reset to initial position."
                    await websocket.send_json(
                        {
                            "type": "chat_response",
                            "role": "assistant",
                            "content": response,
                            "waypoints": [],
                            "intent": intent.intent_type.value,
                            "joint_states": simulator.get_all_joint_states(),
                        }
                    )
                    continue

                # Note: CONVERSATION intent is no longer short-circuited here.
                # Let the LLM handle all messages to allow flexible interpretation.

                # === STAGE 2: Motion Planning ===
                robot_state = simulator.get_all_joint_states() if simulator else {}
                state_description = describe_joint_state(robot_state)

                # Detect special patterns that need hints
                degree_hint = detect_degrees_in_request(user_message)
                plural_hint = detect_plural_arms(user_message)

                # Build context based on intent type
                if intent.intent_type == IntentType.ROLLBACK_AND_RETRY and simulator:
                    # First, rollback to previous state
                    rollback_intent = RollbackIntent(
                        command_type="undo", steps=1, confidence=intent.confidence
                    )
                    await execute_rollback(simulator, state_manager, rollback_intent)

                    # Get fresh state after rollback
                    robot_state = simulator.get_all_joint_states()
                    state_description = describe_joint_state(robot_state)

                    # Build retry context
                    retry_context = build_retry_context(
                        intent,
                        memory.last_user_request or user_message,
                        memory.last_action_summary or "unknown",
                    )
                    contextual_message = (
                        f"{retry_context}\n\n"
                        f"CURRENT_STATE: {json.dumps(robot_state)}\n"
                        f"STATE_DESCRIPTION: {state_description}\n\n"
                        f"USER_REQUEST: {intent.retry_instruction or memory.last_user_request or user_message}"
                    )
                    logger.info(f"Retrying with context: {retry_context[:100]}...")

                elif intent.intent_type == IntentType.CORRECTION:
                    # Correction - modify current state
                    correction_context = build_correction_context(intent, robot_state)
                    contextual_message = (
                        f"{correction_context}\n\n"
                        f"CURRENT_STATE: {json.dumps(robot_state)}\n"
                        f"STATE_DESCRIPTION: {state_description}\n"
                        f"LAST_ACTION: {memory.get_last_waypoints_summary()}\n\n"
                        f"USER_REQUEST: {user_message}"
                    )
                else:
                    # Normal motion command - add hints if detected
                    hints = []
                    if degree_hint:
                        hints.append(degree_hint)
                    if plural_hint:
                        hints.append(plural_hint)

                    hint_block = ""
                    if hints:
                        hint_block = "\n".join(hints) + "\n\n"

                    contextual_message = (
                        f"{hint_block}"
                        f"CURRENT_STATE: {json.dumps(robot_state)}\n"
                        f"STATE_DESCRIPTION: {state_description}\n"
                        f"LAST_ACTION: {memory.get_last_waypoints_summary()}\n\n"
                        f"USER_REQUEST: {user_message}"
                    )

                # --- NEW TWO-AGENT MOTION PLANNING ---
                chat_history = memory.get_context_for_llm()

                # Helper function for the router agent
                def run_router():
                    router_prompt = get_router_prompt().replace(
                        "{primitives_list}", get_primitives_list()
                    )
                    return ollama.chat(
                        model="llama3.2",
                        messages=[
                            {"role": "system", "content": router_prompt},
                            {"role": "user", "content": contextual_message},
                        ],
                        format="json",
                    )["message"]["content"]

                # 1. Call Router
                router_response_text = await asyncio.to_thread(run_router)
                router_data = json.loads(router_response_text)

                # 2. Handle Routing Decision
                response = router_data.get("verbal_response", "Processing request.")

                if router_data.get("status") == "PRIMITIVE":
                    # Easy path! LLM picked a primitive.
                    primitive_name = router_data.get("primitive_name")
                    prim = get_primitive(primitive_name)

                    if prim:
                        # Construct waypoint directly from the primitive data
                        validation = validate_waypoint(prim.joints, clamp=True)
                        wp = Waypoint(
                            joints=validation.validated_joints,
                            speed=1.0,
                            reasoning=router_data.get("reasoning", ""),
                            primitive_name=prim.name,
                        )
                        wp.validation_result = validation
                        waypoints = [wp]
                        logger.info(f"Router selected primitive: {prim.name}")
                    else:
                        logger.warning(
                            f"Router hallucinated primitive: {primitive_name}"
                        )
                        waypoints = []

                elif router_data.get("status") == "RAW_REQUIRED":
                    # Hard path! Call Kinematics agent
                    def run_kinematics():
                        kinematics_prompt = get_kinematics_prompt()
                        return ollama.chat(
                            model="llama3.2",
                            messages=[{"role": "system", "content": kinematics_prompt}]
                            + chat_history
                            + [{"role": "user", "content": contextual_message}],
                            format="json",
                        )["message"]["content"]

                    kinematics_response_text = await asyncio.to_thread(run_kinematics)

                    # Extract waypoints from the kinematics response
                    waypoints = extract_waypoints(kinematics_response_text)

                    # Grab the verbal response from the kinematics agent
                    try:
                        kin_data = json.loads(kinematics_response_text)
                        response = kin_data.get("verbal_response", response)
                    except json.JSONDecodeError:
                        pass
                else:
                    waypoints = []

                # --- CONTINUE WITH EXISTING EXECUTION ---
                executed_waypoints = []
                validation_warnings = []
                sign_warnings = []

                if simulator and waypoints:
                    # Save checkpoint before executing waypoints
                    state_manager.save_checkpoint(
                        simulator, f"before:{user_message[:30]}"
                    )

                    # Collect validation warnings
                    for wp in waypoints:
                        if wp.validation_result and wp.validation_result.had_violations:
                            validation_warnings.extend(wp.validation_result.violations)

                        # Check for sign convention errors
                        motion_sign_issues = validate_motion_sign(
                            user_message, wp.joints
                        )
                        if motion_sign_issues:
                            sign_warnings.extend(motion_sign_issues)
                            for warning in motion_sign_issues:
                                logger.warning(f"Sign validation: {warning}")

                    # Execute waypoints
                    executed_waypoints = await execute_waypoints(simulator, waypoints)

                # Update memory
                waypoints_data = [
                    {
                        "joints": wp.joints,
                        "speed": wp.speed,
                        "reasoning": wp.reasoning,
                        "primitive": wp.primitive_name,
                    }
                    for wp in waypoints
                ]
                memory.add_exchange(user_message, response, waypoints_data)

                # Record the interaction
                recorder.log_interaction(
                    user_message=user_message,
                    assistant_response=response,
                    waypoints_extracted=waypoints_data,
                    waypoints_executed=executed_waypoints,
                )

                # Build response with validation info
                response_data = {
                    "type": "chat_response",
                    "role": "assistant",
                    "content": response,
                    "waypoints": executed_waypoints,
                    "intent": intent.intent_type.value,
                    "joint_states": (
                        simulator.get_all_joint_states() if simulator else None
                    ),
                }

                if validation_warnings:
                    response_data["validation_warnings"] = validation_warnings

                if sign_warnings:
                    response_data["sign_warnings"] = sign_warnings

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
