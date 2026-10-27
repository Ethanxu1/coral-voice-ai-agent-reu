"""WebSocket endpoints for chat, commands, and the sim viewer stream."""

from __future__ import annotations

import asyncio
import base64
import json
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.data.pose_db import list_pose_names
from app.llm.intent_classifier import classify_intent
from app.robot.angle_utils import joints_to_servo_commands
from app.services.chat import (
    HierarchicalMemory,
    _build_pre_context,
    process_chat_message,
    process_conversation_message,
)
from app.services.clean_logger import CleanLogger, close_logger, get_or_create_logger
from app.services.intent import (
    SavePoseDialog,
    _SaveStage,
    handle_save_dialog,
    try_handle_system_intent,
)
from app.services.motion import (
    RobotServerUnavailable,
    _get_robot_state,
    _sync_sim_to_hardware,
    collision_checked_targets,
    convert_state_to_degrees,
    dispatch_servo_commands,
    reset_to_stand,
)
from app.services.recording import ConversationRecorder
from app.services.transcription import transcribe_audio
from app.services.tts import send_chat_response_with_audio
from app.simulator.mujoco_sim import JOG_COMMANDS, command_targets
from app.state import state
from app.validation import describe_joint_state
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

router = APIRouter()

# Store connected websocket clients
connected_clients: set[WebSocket] = set()

# Travel time for /test page buttons: a single-joint jog should feel immediate
# but still glide; a preset pose moves several joints further.
_JOG_DURATION_MS = 400
_PRESET_DURATION_MS = 1000

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


@dataclass
class _Session:
    """Per-connection state for one /ws client."""

    websocket: WebSocket
    session_id: str
    clean_logger: CleanLogger
    memory: HierarchicalMemory = field(default_factory=HierarchicalMemory)
    recorder: ConversationRecorder = field(default_factory=ConversationRecorder)
    save_dialog: SavePoseDialog = field(default_factory=SavePoseDialog)


async def _route_text_turn(
    session: _Session,
    user_message: str,
    source: str,
    pre_context: tuple[dict, str, list] | None = None,
    frontend_intent_type: str | None = None,
    frontend_description: str | None = None,
) -> dict:
    """Classify and dispatch a text utterance using the hybrid intent classifier.

    First tries the regex system-intent fast path; if that misses, asks the LLM
    classifier (the same one used by ``/classify-intent``) and routes by its
    result. This ensures novel child phrasing like "Can you mimic what I do?"
    reaches follow/capture instead of being treated as conversation.
    """
    websocket, memory, clean_logger = session.websocket, session.memory, session.clean_logger
    # Fast regex path for clients that send an explicit immediate intent.
    if frontend_intent_type in (None, "immediate"):
        if await try_handle_system_intent(
            user_message, websocket, session.save_dialog, clean_logger=clean_logger, memory=memory
        ):
            return {"type": "handled_by_system_intent"}

    # Build context for the LLM classifier.
    if pre_context is not None:
        robot_state, state_description, memory_ctx = pre_context
    else:
        robot_state = _get_robot_state()
        state_description = describe_joint_state(robot_state)
        memory_ctx = memory.get_context_for_llm()

    follow_active = (
        state.follow_controller.is_following
        if state.follow_controller is not None
        else False
    )
    intent_result = classify_intent(
        user_message,
        follow_active=follow_active,
        state_degrees=convert_state_to_degrees(robot_state),
        state_description=state_description,
        saved_names=list_pose_names(),
        history=memory_ctx,
    )
    clean_logger.user_message(
        user_message,
        extras={
            "source": source,
            "classified_type": intent_result.get("type"),
            "classified_intent": intent_result.get("intent"),
            "classifier": intent_result.get("classifier"),
        },
    )

    # If the LLM also says immediate, force the system-intent handler with the
    # exact intent it chose.
    if intent_result["type"] == "immediate":
        if await try_handle_system_intent(
            user_message,
            websocket,
            session.save_dialog,
            clean_logger=clean_logger,
            intent_override=intent_result.get("intent"),
            memory=memory,
        ):
            return {"type": "handled_by_system_intent"}

    if intent_result["type"] == "conversation" or frontend_intent_type == "conversation":
        return await process_conversation_message(
            user_message=user_message,
            memory=memory,
            recorder=session.recorder,
            session_id=session.session_id,
        )

    if intent_result["type"] == "motion" or frontend_intent_type == "motion":
        description = frontend_description or intent_result.get("description", user_message)
        try:
            return await process_chat_message(
                user_message=description,
                memory=memory,
                recorder=session.recorder,
                simulator_instance=state.simulator,
                session_id=session.session_id,
                pre_context=pre_context,
            )
        except RobotServerUnavailable:
            return {
                "type": "chat_response",
                "role": "assistant",
                "content": _CHILD_FRIENDLY_ERRORS["robot_unavailable"],
                "waypoints": [],
            }

    if intent_result["type"] == "clarification":
        return {
            "type": "chat_response",
            "role": "assistant",
            "content": intent_result.get("question", "Can you say that another way?"),
            "waypoints": [],
            "joint_states": _get_robot_state() or None,
        }

    # Unknown/unsupported result shape: fall back to the motion planner, which
    # has its own deterministic fallback.
    return await process_chat_message(
        user_message=user_message,
        memory=memory,
        recorder=session.recorder,
        simulator_instance=state.simulator,
        session_id=session.session_id,
        pre_context=pre_context,
    )


async def _handle_text_turn(
    session: _Session,
    text: str,
    source: str,
    pre_context: tuple[dict, str, list] | None = None,
    intent_type: str | None = None,
    description: str | None = None,
) -> None:
    """Answer one child utterance: save-pose dialog first, then intent routing."""
    if session.save_dialog.stage != _SaveStage.IDLE:
        if await handle_save_dialog(text, session.save_dialog, session.websocket):
            return

    response_data = await _route_text_turn(
        session,
        text,
        source,
        pre_context=pre_context,
        frontend_intent_type=intent_type,
        frontend_description=description,
    )
    if response_data.get("type") == "handled_by_system_intent":
        return
    await send_chat_response_with_audio(session.websocket, response_data)
    session.clean_logger.agent_response(
        response_data.get("content", ""),
        response_type=response_data.get("type", "chat_response"),
        extras={
            "waypoints": len(response_data.get("waypoints", [])),
            "safety": response_data.get("safety"),
        },
    )


async def _handle_chat(session: _Session, message: dict) -> None:
    await _handle_text_turn(
        session,
        message.get("content", ""),
        source="typed/chat",
        intent_type=message.get("intent_type"),
        description=message.get("description"),
    )


async def _handle_audio(session: _Session, message: dict) -> None:
    audio_bytes = base64.b64decode(message.get("data", ""))

    # Speech-to-text only: the caller owns what happens next.
    if message.get("transcribe_only") is True:
        text = await asyncio.to_thread(transcribe_audio, audio_bytes)
        session.clean_logger.user_message(text, extras={"source": "audio-transcribe-only"})
        await session.websocket.send_json({"type": "transcription", "text": text})
        return

    text, pre_context = await asyncio.gather(
        asyncio.to_thread(transcribe_audio, audio_bytes),
        _build_pre_context(state.simulator, session.memory),
    )
    await session.websocket.send_json({"type": "transcription", "text": text})
    session.clean_logger.user_message(text, extras={"source": "audio"})
    if text.strip():
        await _handle_text_turn(session, text, source="audio", pre_context=pre_context)


async def _handle_command(session: _Session, message: dict) -> None:
    """Run a /test page button: reset, sim↔hardware sync, or a jog/preset."""
    command = message.get("command", "")
    sim = state.simulator
    success = False
    safety_report: dict[str, Any] = {}

    if sim is None:
        pass
    elif command in ("reset", "stand"):
        await reset_to_stand()
        success = True
    elif command == "sync_sim":
        # Snap the sim viewer to the robot's current pose without moving the robot.
        await asyncio.to_thread(_sync_sim_to_hardware)
        success = True
    elif (targets := command_targets(sim, command)) is not None:
        # Same path as every other motion: collision-check the target first,
        # then dispatch it as a timed move so the sim (and robot) glide there.
        # No fall check: the Joint test page pins the sim upright instead.
        safe_targets, safety_report = await asyncio.to_thread(
            collision_checked_targets, sim, targets, f"/test command '{command}'", False
        )
        duration_ms = _JOG_DURATION_MS if command in JOG_COMMANDS else _PRESET_DURATION_MS
        try:
            await dispatch_servo_commands(
                joints_to_servo_commands(safe_targets, duration_ms), sim_only=None
            )
        except RobotServerUnavailable as e:
            logger.warning(f"/test command '{command}': robot server unavailable: {e}")
        success = True

    await session.websocket.send_json(
        {
            "type": "command_result",
            "success": success,
            "command": command,
            "collision_clamped": safety_report.get("collision_clamped", False),
            "fall_blocked": safety_report.get("fall_blocked", False),
            "bad_pairs": safety_report.get("bad_pairs", []),
            "joint_states": _get_robot_state() if success else None,
        }
    )


_HANDLERS = {
    "chat": _handle_chat,
    "audio": _handle_audio,
    "command": _handle_command,
}


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for chat and real-time updates."""
    await websocket.accept()
    connected_clients.add(websocket)
    logger.info(f"WebSocket client connected. Total clients: {len(connected_clients)}")

    # Allow the client to supply a stable session ID so intent classification HTTP
    # calls and websocket chat turns group together in Langfuse.
    session_id = (
        websocket.query_params.get("session_id")
        or f"ws-{id(websocket)}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    )
    session = _Session(
        websocket=websocket,
        session_id=session_id,
        clean_logger=get_or_create_logger(session_id),
    )
    clean_logger = session.clean_logger

    try:
        while True:
            message = json.loads(await websocket.receive_text())
            handler = _HANDLERS.get(message.get("type", "chat"))
            if handler is None:
                logger.warning(f"Ignoring unknown /ws message type: {message.get('type')!r}")
                continue
            await handler(session, message)

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
        clean_logger.websocket_event("disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        traceback.print_exc()
        clean_logger.error(f"WebSocket error: {e}", e)
        try:
            await send_chat_response_with_audio(
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
        if (
            state.follow_controller is not None
            and state.follow_controller.is_following
            and state.follow_controller.owner is websocket
        ):
            await state.follow_controller.stop_follow(
                reason="websocket closing", clean_logger=clean_logger
            )
        close_logger(session_id)
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
