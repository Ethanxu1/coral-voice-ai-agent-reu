"""FastAPI server for the Coral AI agent with MuJoCo simulation."""

import asyncio
import json
import re
from contextlib import asynccontextmanager
from typing import Any

import ollama
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pydantic import BaseModel

from coral_agent.simulator import ApolloSimulator
from coral_agent.simulator.mujoco_sim import COMMAND_MAP, execute_command

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


def extract_commands(text: str) -> list[str]:
    """Extract robot commands from LLM response text.

    Looks for commands in format [COMMAND:action] or common phrases.
    """
    commands = []

    # Pattern 1: Explicit command tags [COMMAND:action]
    pattern = r"\[COMMAND:(\w+)\]"
    matches = re.findall(pattern, text, re.IGNORECASE)
    commands.extend(matches)

    # Pattern 2: Natural language command extraction
    text_lower = text.lower()

    # Map natural language to commands
    nl_mappings = [
        # Head movements (independent!)
        (r"turn.*head.*left|head.*left", "head_left"),
        (r"turn.*head.*right|head.*right", "head_right"),
        (r"look.*up|head.*up|tilt.*head.*up", "head_up"),
        (r"look.*down|head.*down|tilt.*head.*down", "head_down"),
        # Torso movements (separate from head)
        (r"rotate.*torso.*left|turn.*body.*left|torso.*left", "torso_left"),
        (r"rotate.*torso.*right|turn.*body.*right|torso.*right", "torso_right"),
        (r"lean.*forward|bow", "lean_forward"),
        (r"lean.*back", "lean_backward"),
        (r"lean.*left", "lean_left"),
        (r"lean.*right", "lean_right"),
        # Arm movements
        (r"raise.*left.*arm|left.*arm.*up|lift.*left.*arm", "left_arm_up"),
        (r"lower.*left.*arm|left.*arm.*down", "left_arm_down"),
        (r"raise.*right.*arm|right.*arm.*up|lift.*right.*arm", "right_arm_up"),
        (r"lower.*right.*arm|right.*arm.*down", "right_arm_down"),
        (r"move.*left.*arm.*out|left.*arm.*outward", "left_arm_out"),
        (r"move.*left.*arm.*in|left.*arm.*inward", "left_arm_in"),
        (r"move.*right.*arm.*out|right.*arm.*outward", "right_arm_out"),
        (r"move.*right.*arm.*in|right.*arm.*inward", "right_arm_in"),
        (r"bend.*left.*elbow", "left_elbow_bend"),
        (r"extend.*left.*elbow|straighten.*left.*elbow", "left_elbow_extend"),
        (r"bend.*right.*elbow", "right_elbow_bend"),
        (r"extend.*right.*elbow|straighten.*right.*elbow", "right_elbow_extend"),
        # Gestures
        (r"\bwave\b|waving", "wave"),
        (r"\bpoint\b|pointing", "point"),
        (r"look.*around", "look_around"),
        (r"\bnod\b|nodding|yes", "nod"),
        (r"\bshake\b.*head|shaking.*head|say.*no", "shake"),
        (r"\breset\b|default.*pose|standing.*pose", "reset"),
    ]

    for pattern, cmd in nl_mappings:
        if re.search(pattern, text_lower):
            if cmd not in commands:
                commands.append(cmd)

    return commands


def get_llm_response(user_message: str, history: list[dict]) -> str:
    """Get response from Ollama LLM (synchronous - run in thread)."""
    system_prompt = """You are a helpful robot assistant controlling an Apptronik Apollo humanoid robot.
When the user asks you to perform physical actions, include the command in your response using [COMMAND:action] format.

Available commands:

HEAD (independent):
- [COMMAND:head_left] - Turn head left
- [COMMAND:head_right] - Turn head right
- [COMMAND:head_up] - Tilt head up
- [COMMAND:head_down] - Tilt head down

TORSO (separate from head):
- [COMMAND:torso_left] - Rotate torso left
- [COMMAND:torso_right] - Rotate torso right
- [COMMAND:lean_forward] - Lean torso forward
- [COMMAND:lean_backward] - Lean torso backward
- [COMMAND:lean_left] - Lean torso left
- [COMMAND:lean_right] - Lean torso right

ARMS:
- [COMMAND:left_arm_up] - Raise left arm
- [COMMAND:left_arm_down] - Lower left arm
- [COMMAND:left_arm_out] - Move left arm outward
- [COMMAND:left_arm_in] - Move left arm inward
- [COMMAND:left_elbow_bend] - Bend left elbow
- [COMMAND:left_elbow_extend] - Extend left elbow
- [COMMAND:right_arm_up] - Raise right arm
- [COMMAND:right_arm_down] - Lower right arm
- [COMMAND:right_arm_out] - Move right arm outward
- [COMMAND:right_arm_in] - Move right arm inward
- [COMMAND:right_elbow_bend] - Bend right elbow
- [COMMAND:right_elbow_extend] - Extend right elbow

GESTURES:
- [COMMAND:wave] - Wave gesture
- [COMMAND:point] - Point forward
- [COMMAND:look_around] - Look around
- [COMMAND:nod] - Nod head (yes)
- [COMMAND:shake] - Shake head (no)
- [COMMAND:reset] - Reset to standing pose

Example:
User: "Can you wave at me?"
Assistant: "Of course! I'll wave at you. [COMMAND:wave]"

User: "Look at me and nod"
Assistant: "I'm looking at you now. [COMMAND:head_up] Yes, I understand! [COMMAND:nod]"

Be friendly and conversational while helping with robot control tasks."""

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

                # Get LLM response
                response = await asyncio.to_thread(
                    get_llm_response, user_message, chat_history
                )

                # Update history
                chat_history.append({"role": "user", "content": user_message})
                chat_history.append({"role": "assistant", "content": response})

                # Keep history manageable
                if len(chat_history) > 20:
                    chat_history = chat_history[-20:]

                # Extract and execute commands
                commands = extract_commands(response)
                executed_commands = []

                if simulator and commands:
                    for cmd in commands:
                        if execute_command(simulator, cmd):
                            executed_commands.append(cmd)

                # Send response back
                await websocket.send_json(
                    {
                        "type": "chat_response",
                        "role": "assistant",
                        "content": response,
                        "commands": executed_commands,
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
