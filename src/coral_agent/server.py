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

from coral_agent.simulator import ApolloSimulator
from coral_agent.simulator.mujoco_sim import COMMAND_MAP, execute_command

# Setup recordings directory
RECORDINGS_DIR = Path(__file__).parent.parent.parent / "recordings"
RECORDINGS_DIR.mkdir(exist_ok=True)

# Global simulator instance
simulator: ApolloSimulator | None = None


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

    def __init__(self, joints: dict[str, float], speed: float = 1.0):
        self.joints = joints  # {"joint_name": target_position}
        self.speed = max(0.1, min(speed, 5.0))  # Clamp speed between 0.1 and 5.0


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

    Looks for waypoints in format [WAYPOINT: {"joint": value, ...}, speed]
    or [WAYPOINT: {"joint": value, ...}] (speed defaults to 1.0)
    """
    waypoints = []

    # Pattern to match [WAYPOINT: {json}, optional_speed]
    # Handles both with and without speed parameter
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
            waypoints.append(Waypoint(joints=joints, speed=speed))
            logger.info(f"Extracted waypoint: joints={joints}, speed={speed}")
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse waypoint JSON: {joints_str}, error: {e}")
        except Exception as e:
            logger.warning(f"Failed to process waypoint: {e}")

    return waypoints


async def execute_waypoints(
    simulator: ApolloSimulator, waypoints: list[Waypoint]
) -> list[dict]:
    """Execute a sequence of waypoints with interpolation.

    Each waypoint is reached by interpolating from current position to target.
    Speed determines how fast the interpolation happens (higher = faster).

    Returns a list of executed waypoint info.
    """
    executed = []
    base_steps = 20  # Base number of interpolation steps at speed=1.0
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

        executed.append({
            "waypoint_index": i,
            "joints": waypoint.joints,
            "speed": waypoint.speed,
        })
        logger.info(f"Executed waypoint {i}: {waypoint.joints} at speed {waypoint.speed}")

    return executed


def get_llm_response(user_message: str, history: list[dict]) -> str:
    """Get response from Ollama LLM (synchronous - run in thread)."""
    system_prompt = """You control an Apptronik Apollo humanoid robot by outputting WAYPOINTS.

### WAYPOINT FORMAT:
[WAYPOINT: {"joint": value, "joint2": value2}, speed]
- Combine related joints in ONE waypoint for coordinated movement
- Speed: 0.5=slow, 1.0=normal, 2.0+=fast
- NEVER exceed joint limits!

### JOINT REFERENCE (values in radians):

HEAD:
- neck_yaw: [-0.7, 0.7] → positive=look LEFT, negative=look RIGHT
- neck_pitch: [-0.5, 0.5] → positive=look DOWN, negative=look UP

TORSO:
- torso_yaw: [-0.6, 0.6] → positive=rotate RIGHT, negative=rotate LEFT
- torso_pitch: [-0.3, 0.5] → positive=lean FORWARD, negative=lean BACK
- torso_roll: [-0.3, 0.3] → positive=lean RIGHT, negative=lean LEFT

LEFT ARM:
- l_shoulder_fe: [-1.5, 1.5] → negative=arm FORWARD/UP, positive=arm BACK
- l_shoulder_aa: [-0.3, 2.0] → positive=arm OUT (away from body), negative=arm IN
- l_elbow: [-2.0, 0.0] → negative=BEND elbow, 0=straight

RIGHT ARM:
- r_shoulder_fe: [-1.5, 1.5] → negative=arm FORWARD/UP, positive=arm BACK
- r_shoulder_aa: [-2.0, 0.3] → negative=arm OUT (away from body), positive=arm IN
- r_elbow: [-2.0, 0.0] → negative=BEND elbow, 0=straight

NOTE: Left and right shoulder_aa have OPPOSITE signs for outward movement!
- Left arm outward: l_shoulder_aa = POSITIVE (e.g., 1.5)
- Right arm outward: r_shoulder_aa = NEGATIVE (e.g., -1.5)

### CRITICAL RULES:
1. ALWAYS check CURRENT_STATE before moving - use it to return to previous positions
2. NEVER output values outside joint limits
3. Combine related joints (e.g., shoulder + elbow) in ONE waypoint
4. Keep responses SHORT - just describe the action briefly
5. For "raise arm outward/sideways": use shoulder_aa (NOT shoulder_fe)
6. For "raise arm forward/up": use shoulder_fe with negative values

### EXAMPLES:

Right arm out to side (T-pose style):
"Raising right arm out. [WAYPOINT: {"r_shoulder_fe": -1.5, "r_shoulder_aa": -1.5, "r_elbow": 0.0}, 1.0]"

Left arm out to side:
"Raising left arm out. [WAYPOINT: {"l_shoulder_fe": -1.5, "l_shoulder_aa": 1.5, "l_elbow": 0.0}, 1.0]"

Both arms T-pose:
"T-pose! [WAYPOINT: {"l_shoulder_fe": -1.5, "l_shoulder_aa": 1.5, "r_shoulder_fe": -1.5, "r_shoulder_aa": -1.5, "l_elbow": 0.0, "r_elbow": 0.0}, 1.0]"

Return to neutral (check CURRENT_STATE for original values, typically near 0):
"Returning to neutral. [WAYPOINT: {"l_shoulder_fe": 0.0, "l_shoulder_aa": 0.0, "r_shoulder_fe": 0.0, "r_shoulder_aa": 0.0, "l_elbow": 0.0, "r_elbow": 0.0}, 1.0]"

Wave hello:
"Waving! [WAYPOINT: {"r_shoulder_fe": -1.0, "r_shoulder_aa": -0.5, "r_elbow": -1.2}, 1.0]"

Look right slowly:
"Looking right. [WAYPOINT: {"neck_yaw": -0.5}, 0.5]"
"""
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    try:
        logger.info(f"Sending to Ollama: {user_message[:50]}...")
        response = ollama.chat(model="llama3.2", messages=messages)
        content = response["message"]["content"]
        logger.info(f"Ollama response: {content[:50]}...")
        return content
    except ollama.ResponseError as e:
        logger.error(f"Ollama response error: {e}")
        return f"Ollama error: {e}. Make sure the model 'llama3.2' is installed (run: ollama pull llama3.2)"
    except Exception as e:
        logger.error(f"Ollama connection error: {e}")
        return f"Cannot connect to Ollama. Make sure Ollama is running (run: ollama serve). Error: {e}"


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


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for chat and real-time updates."""
    global simulator

    await websocket.accept()
    connected_clients.add(websocket)
    logger.info(f"WebSocket client connected. Total clients: {len(connected_clients)}")

    # Maintain chat history for this connection
    chat_history: list[dict] = []

    # Create a recorder for this session
    recorder = ConversationRecorder()

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
                # Chat message - get LLM response
                user_message = message_data.get("content", "")

                # Get current robot state as flat dict
                robot_state = simulator.get_all_joint_states()

                # Format state for LLM context
                contextual_message = f"CURRENT_STATE: {json.dumps(robot_state)}\n\nUSER_REQUEST: {user_message}"

                # Get LLM response
                response = await asyncio.to_thread(
                    get_llm_response, contextual_message, chat_history
                )

                # Update history (store original user message, not contextual)
                chat_history.append({"role": "user", "content": user_message})
                chat_history.append({"role": "assistant", "content": response})

                # Keep history manageable
                if len(chat_history) > 20:
                    chat_history = chat_history[-20:]

                # Extract and execute waypoints
                waypoints = extract_waypoints(response)
                executed_waypoints = []

                if simulator and waypoints:
                    executed_waypoints = await execute_waypoints(simulator, waypoints)

                # Record the interaction
                waypoints_extracted = [
                    {"joints": wp.joints, "speed": wp.speed} for wp in waypoints
                ]
                recorder.log_interaction(
                    user_message=user_message,
                    assistant_response=response,
                    waypoints_extracted=waypoints_extracted,
                    waypoints_executed=executed_waypoints,
                )

                # Send response back
                await websocket.send_json(
                    {
                        "type": "chat_response",
                        "role": "assistant",
                        "content": response,
                        "waypoints": executed_waypoints,
                        "joint_states": (
                            simulator.get_all_joint_states() if simulator else None
                        ),
                    }
                )

            elif msg_type == "get_state":
                # Request current robot state
                if simulator:
                    await websocket.send_json(
                        {
                            "type": "state",
                            "joint_states": simulator.get_all_joint_states(),
                            "running": simulator.is_running(),
                        }
                    )

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
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
