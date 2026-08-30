"""WebSocket endpoints for chat, commands, and the sim viewer stream."""

from __future__ import annotations

import asyncio
import base64
import json
import traceback
from datetime import datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from app.robot.angle_utils import rad_to_servo_units
from app.robot.interface import ServoCommand
from app.robot.servo_config import SERVO_ID_MAP
from app.services.chat import (
    HierarchicalMemory,
    _build_pre_context,
    process_chat_message,
    process_conversation_message,
)
from app.services.intent import SavePoseDialog, _SaveStage, handle_save_dialog, try_handle_system_intent
from app.services.motion import (
    RESET_TO_STAND_MS,
    RobotServerUnavailable,
    _get_robot_state,
    _sync_sim_to_hardware,
    dispatch_servo_commands,
)
from app.services.recording import ConversationRecorder
from app.services.transcription import transcribe_audio
from app.services.tts import generate_speech
from app.simulator.mujoco_sim import execute_command
from app.state import state
from app.state_manager import StateManager
from app.validation import describe_joint_state

if TYPE_CHECKING:
    pass

router = APIRouter()

# Store connected websocket clients
connected_clients: set[WebSocket] = set()


# Child-friendly error copy so a failure feels recoverable, not scary.
_CHILD_FRIENDLY_ERRORS = {
    "robot_unavailable": (
        "I moved in the simulator, but I couldn't reach the physical robot. "
        "Make sure it's turned on and connected."
    ),
    "generic": (
        "Oops, my brain hiccuped. Can you try that again?"
    ),
}


async def _send_response_with_audio(
    websocket: WebSocket, response_data: dict
) -> None:
    """Send a chat response, then synthesize and send audio for its text."""
    await websocket.send_json(response_data)

    text = response_data.get("content", "")
    audio = await asyncio.to_thread(generate_speech, text)
    if audio is not None:
        await websocket.send_json(
            {
                "type": "audio_response",
                "audio_base64": base64.b64encode(audio).decode("utf-8"),
                "format": "mp3",
            }
        )


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for chat and real-time updates."""
    await websocket.accept()
    connected_clients.add(websocket)
    logger.info(f"WebSocket client connected. Total clients: {len(connected_clients)}")

    # Initialize per-connection state
    memory = HierarchicalMemory()
    state_manager = StateManager(max_checkpoints=10)
    recorder = ConversationRecorder()
    save_dialog = SavePoseDialog()
    # Allow the client to supply a stable session ID so intent classification HTTP
    # calls and websocket chat turns group together in Langfuse.
    session_id = (
        websocket.query_params.get("session_id")
        or f"ws-{id(websocket)}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    )

    # Save initial state as checkpoint
    if state.simulator:
        state_manager.save_checkpoint(state.simulator, "session_start")

    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            message_data = json.loads(data)

            msg_type = message_data.get("type", "chat")

            if msg_type == "command":
                command = message_data.get("command", "")
                success = False

                if command in ("reset", "stand") and state.simulator is not None:
                    state_manager.save_checkpoint(state.simulator, "before_command:reset")
                    # Sim: place the robot upright slightly above the floor and let
                    # physics drop it into a stable stand — re-stands a fallen robot,
                    # which animating the joints alone cannot.
                    await asyncio.to_thread(state.simulator.reset_pose)
                    # Hardware: can't teleport a physical robot, so animate its
                    # joints to the stand pose over a smooth interval.
                    if state.hardware_dispatcher is not None:
                        stand = state.simulator.get_stand_joint_positions()
                        cmds = [
                            ServoCommand(
                                servo_id=sid,
                                position=rad_to_servo_units(rad),
                                duration_ms=RESET_TO_STAND_MS,
                            )
                            for joint, rad in stand.items()
                            if (sid := SERVO_ID_MAP.get(joint)) is not None
                        ]
                        if cmds:
                            await asyncio.to_thread(
                                state.hardware_dispatcher.send_commands, cmds
                            )
                    success = True

                elif command == "sync_sim":
                    # Instantly snap the sim viewer to the robot's current pose without
                    # sending any commands to the physical robot.
                    if state.simulator is not None:
                        await asyncio.to_thread(_sync_sim_to_hardware)
                        success = True

                elif state.simulator is not None:
                    state_manager.save_checkpoint(
                        state.simulator, f"before_command:{command}"
                    )
                    before = state.simulator.get_all_joint_states()
                    success = execute_command(state.simulator, command)
                    if success and state.hardware_dispatcher is not None:
                        after = state.simulator.get_all_joint_states()
                        servo_cmds = []
                        for joint, new_rad in after.items():
                            if abs(new_rad - before.get(joint, 0.0)) > 1e-4:
                                sid = SERVO_ID_MAP.get(joint)
                                if sid is None:
                                    continue
                                servo_cmds.append(
                                    ServoCommand(
                                        servo_id=sid,
                                        position=rad_to_servo_units(new_rad),
                                        duration_ms=400,
                                    )
                                )
                        if servo_cmds:
                            await asyncio.to_thread(
                                state.hardware_dispatcher.send_commands, servo_cmds
                            )

                await websocket.send_json(
                    {
                        "type": "command_result",
                        "success": success,
                        "command": command,
                        "joint_states": _get_robot_state() if success else None,
                    }
                )

            elif msg_type == "chat":
                # Chat message - process with full Langfuse tracing
                user_message = message_data.get("content", "")
                intent_type = message_data.get("intent_type")
                motion_description = message_data.get("description")
                if save_dialog.stage != _SaveStage.IDLE:
                    if await handle_save_dialog(user_message, save_dialog, websocket):
                        continue
                # The regex system-intent matcher is for clients that hand us raw
                # speech and let us decide what it means. A client that sends an
                # explicit intent_type has already classified this turn and owns
                # the flow, so re-matching here would fight it.
                if intent_type in (None, "immediate"):
                    if await try_handle_system_intent(
                        user_message, websocket, save_dialog
                    ):
                        continue

                # Route conversation/clarification to the chat LLM and finalized
                # motion descriptions to the motion planner.
                if intent_type == "conversation":
                    response_data = await process_conversation_message(
                        user_message=user_message,
                        memory=memory,
                        recorder=recorder,
                        session_id=session_id,
                    )
                elif intent_type == "motion" and motion_description:
                    try:
                        response_data = await process_chat_message(
                            user_message=motion_description,
                            memory=memory,
                            state_manager=state_manager,
                            recorder=recorder,
                            simulator_instance=state.simulator,
                            session_id=session_id,
                            on_action_started=lambda: websocket.send_json(
                                {"type": "action_started"}
                            ),
                        )
                    except RobotServerUnavailable:
                        response_data = {
                            "type": "chat_response",
                            "role": "assistant",
                            "content": _CHILD_FRIENDLY_ERRORS["robot_unavailable"],
                            "waypoints": [],
                        }
                else:
                    response_data = await process_chat_message(
                        user_message=user_message,
                        memory=memory,
                        state_manager=state_manager,
                        recorder=recorder,
                        simulator_instance=state.simulator,
                        session_id=session_id,
                        on_action_started=lambda: websocket.send_json(
                            {"type": "action_started"}
                        ),
                    )
                await _send_response_with_audio(websocket, response_data)

            elif msg_type == "audio":
                audio_b64 = message_data.get("data", "")
                audio_bytes = base64.b64decode(audio_b64)
                # Speech-to-text only: the caller owns what happens next.
                transcribe_only = message_data.get("transcribe_only") is True
                if transcribe_only:
                    transcribed_text = await asyncio.to_thread(transcribe_audio, audio_bytes)
                    await websocket.send_json(
                        {"type": "transcription", "text": transcribed_text}
                    )
                    continue
                transcribed_text, pre_context = await asyncio.gather(
                    asyncio.to_thread(transcribe_audio, audio_bytes),
                    _build_pre_context(state.simulator, memory),
                )
                await websocket.send_json(
                    {"type": "transcription", "text": transcribed_text}
                )
                if transcribed_text.strip():
                    if save_dialog.stage != _SaveStage.IDLE:
                        if await handle_save_dialog(
                            transcribed_text, save_dialog, websocket
                        ):
                            continue
                    if await try_handle_system_intent(
                        transcribed_text, websocket, save_dialog
                    ):
                        continue
                    response_data = await process_chat_message(
                        user_message=transcribed_text,
                        memory=memory,
                        state_manager=state_manager,
                        recorder=recorder,
                        simulator_instance=state.simulator,
                        session_id=session_id,
                        pre_context=pre_context,
                        on_action_started=lambda: websocket.send_json(
                            {"type": "action_started"}
                        ),
                    )
                    await _send_response_with_audio(websocket, response_data)

            elif msg_type == "get_state":
                robot_state = await asyncio.to_thread(_get_robot_state)
                await websocket.send_json(
                    {
                        "type": "state",
                        "joint_states": robot_state,
                        "state_description": describe_joint_state(robot_state),
                        "checkpoint_count": state_manager.checkpoint_count,
                        "running": state.simulator.is_running()
                        if state.simulator is not None
                        else True,
                    }
                )

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        traceback.print_exc()
        try:
            await _send_response_with_audio(
                websocket,
                {
                    "type": "chat_response",
                    "role": "assistant",
                    "content": _CHILD_FRIENDLY_ERRORS["generic"],
                    "waypoints": [],
                    "joint_states": _get_robot_state() or None,
                },
            )
        except Exception:
            pass
    finally:
        connected_clients.discard(websocket)
        if state.follow_controller is not None and state.follow_controller.is_following:
            await state.follow_controller.stop_follow()
        logger.info(
            f"WebSocket client removed. Total clients: {len(connected_clients)}"
        )


@router.websocket("/ws/sim")
async def sim_stream_endpoint(websocket: WebSocket):
    """Stream MuJoCo geom world poses to the browser viewer (RobotViewer.tsx)."""
    await websocket.accept()
    if state.simulator is None:
        await websocket.send_json(
            {"type": "error", "detail": "simulator not initialized"}
        )
        await websocket.close()
        return

    await websocket.send_json(
        {
            "type": "init",
            "mesh_url": "/assets/ainex/meshes/",
            "geoms": state.simulator.get_render_geom_info(),
            "joints": state.simulator.get_joint_metadata(),
        }
    )
    logger.info("Sim viewer client connected")

    fps = 30
    # Send live joint frames at ~5 Hz.
    joint_frame_interval = 6
    frame_count = 0
    try:
        while True:
            await websocket.send_bytes(state.simulator.get_geom_poses())
            frame_count += 1
            if frame_count % joint_frame_interval == 0:
                await websocket.send_json(
                    {
                        "type": "joints",
                        "joints": state.simulator.get_joint_frames(),
                    }
                )
            await asyncio.sleep(1 / fps)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        logger.info("Sim viewer client disconnected")
