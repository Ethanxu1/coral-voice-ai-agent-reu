"""System intent classification and save-pose dialog handling."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from fastapi import WebSocket
from loguru import logger

from app.data.pose_db import get_pose, list_pose_names, save_pose
from app.services.motion import _execute_on_hardware_if_connected, _get_robot_state
from app.services.tts import send_chat_response_with_audio
from app.state import state

if TYPE_CHECKING:
    from app.services.chat import HierarchicalMemory


class _SaveStage(Enum):
    IDLE = "idle"
    AWAITING_CONFIRM = "awaiting_confirm"
    AWAITING_NAME = "awaiting_name"


@dataclass
class SavePoseDialog:
    stage: _SaveStage = _SaveStage.IDLE
    pending_joints: dict[str, float] | None = None


_YES_RE = re.compile(
    r"\b(yes|yeah|yep|yup|sure|ok|okay|go ahead|do it)\b", re.IGNORECASE
)
_NO_RE = re.compile(
    r"\b(no|nope|nah|cancel|never mind|nevermind|stop)\b", re.IGNORECASE
)


async def handle_save_dialog(
    text: str, dialog: SavePoseDialog, websocket: WebSocket
) -> bool:
    """Handle a turn within the save-pose multi-turn dialog.

    Returns True if the message was consumed by the dialog (caller should skip LLM).
    """
    if dialog.stage == _SaveStage.AWAITING_CONFIRM:
        if _YES_RE.search(text):
            dialog.stage = _SaveStage.AWAITING_NAME
            await send_chat_response_with_audio(
                websocket,
                {
                    "type": "chat_response",
                    "role": "assistant",
                    "content": "What would you like to name this pose?",
                    "waypoints": [],
                    "joint_states": _get_robot_state() or None,
                }
            )
        elif _NO_RE.search(text):
            dialog.stage = _SaveStage.IDLE
            dialog.pending_joints = None
            await send_chat_response_with_audio(
                websocket,
                {
                    "type": "chat_response",
                    "role": "assistant",
                    "content": "OK, I won't save the position.",
                    "waypoints": [],
                    "joint_states": _get_robot_state() or None,
                }
            )
        else:
            await send_chat_response_with_audio(
                websocket,
                {
                    "type": "chat_response",
                    "role": "assistant",
                    "content": "Should I save this position? Say yes or no.",
                    "waypoints": [],
                    "joint_states": _get_robot_state() or None,
                }
            )
        return True

    if dialog.stage == _SaveStage.AWAITING_NAME:
        name = re.sub(r"[^\w\s\-]", "", text).strip()
        if not name:
            await send_chat_response_with_audio(
                websocket,
                {
                    "type": "chat_response",
                    "role": "assistant",
                    "content": "I didn't catch a name. What should I call this pose?",
                    "waypoints": [],
                    "joint_states": _get_robot_state() or None,
                }
            )
            return True
        joints = dialog.pending_joints or {}
        save_pose(name, joints)
        await _execute_on_hardware_if_connected(joints)
        dialog.stage = _SaveStage.IDLE
        dialog.pending_joints = None
        await send_chat_response_with_audio(
            websocket,
            {
                "type": "chat_response",
                "role": "assistant",
                "content": f"Saved as {name}.",
                "waypoints": [],
                "joint_states": _get_robot_state() or None,
            }
        )
        return True

    return False


_FOLLOW_START_RE = re.compile(
    r"\b(follow|mimic|copy|mirror)\b.*\b(movement|movements|me|my\s+(moves|movements))\b"
    r"|\bfollow\s+me\b"
    r"|\bmirror\s+me\b"
    r"|\bcopy\s+me\b",
    re.IGNORECASE,
)
# Stop commands are matched without requiring follow_active: stop_follow is a
# no-op when not following, and a user saying "stop following" after a follow
# loop has already crashed/ended must still be handled as a system command
# instead of falling through to the motion planner.
_FOLLOW_STOP_RE = re.compile(
    r"\bstop\b(\s+(following|mimicking|copying|mirroring))?\b|\bquit\s+follow\b",
    re.IGNORECASE,
)
_CAPTURE_RE = re.compile(
    r"\b(capture|take|copy|record)\b.*\b(pose|position|picture|snapshot|photo)\b"
    r"|\btake\s+a\s+picture\b"
    r"|\btake\s+a\s+snapshot\b"
    r"|\bpicture\s+of\s+me\b"
    r"|\bfreeze\b"
    r"|\block\s+it\s+in\b"
    r"|\bi\s+want\s+you\s+to\s+(take|capture|record|copy)\b",
    re.IGNORECASE,
)
_SAVE_POSE_RE = re.compile(
    r"\b(save|remember|store|keep)\b.*(position|pose|this)\b"
    r"|\bremember\s+this\b"
    r"|\bsave\s+this\b"
    r"|\bkeep\s+this\s+pose\b",
    re.IGNORECASE,
)
# Play a saved pose. We detect the intent here; the exact name is resolved with
# fuzzy matching against list_pose_names() because kids rarely say the exact
# stored name.
_PLAY_POSE_RE = re.compile(
    # Broad: "perform right arm up", "play my superhero pose", "strike the pose".
    # The name is resolved downstream with fuzzy matching against saved poses.
    r"\b(play|perform|strike|show)\s+(?:the\s+)?(?:my\s+)?(.+?)(?:\s+pose)?$"
    r"|\b(play|do|perform|strike|show)\b.*\b(my\s+)?(pose|saved pose)\b"
    r"|\b(play|do|perform|strike|show)\s+(?:the\s+)?pose\s+(.+)$",
    re.IGNORECASE,
)


def _extract_pose_name(text: str) -> str:
    """Best-effort extraction of a pose name from a play-pose utterance."""
    # Strip the leading verb phrase and common filler words.
    cleaned = re.sub(
        r"^\s*(can you|please|will you|could you|would you|now|okay|so|then)\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\b(play|do|perform|strike|show|the|my|a|pose|saved)\b",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .!?,'\"")
    return cleaned


def _resolve_pose_name(text: str) -> tuple[str | None, list[str]]:
    """Fuzzy-match the utterance to a saved pose name.

    Returns (matched_name, all_names). If no good match, matched_name is None.
    """
    all_names = list_pose_names()
    if not all_names:
        return None, []
    exact_lower = {n.lower(): n for n in all_names}
    extracted = _extract_pose_name(text)
    # Exact match first (case-insensitive).
    if extracted.lower() in exact_lower:
        return exact_lower[extracted.lower()], all_names
    # Then difflib on the extracted candidate.
    close = difflib.get_close_matches(extracted, all_names, n=1, cutoff=0.6)
    if close:
        return close[0], all_names
    # Finally difflib on the full utterance in case the name is embedded.
    close = difflib.get_close_matches(text, all_names, n=1, cutoff=0.5)
    if close:
        return close[0], all_names
    return None, all_names


def classify_system_intent(text: str) -> str | None:
    """Match voice/chat input to a follow/capture/save/play system action.

    Returns one of {"follow_start", "follow_stop", "capture_pose",
    "play_pose", "save_current_pose"} or None to fall through to the LLM
    motion planner. Stop-follow matching no longer requires an active follow
    loop: calling stop_follow when not following is a safe no-op, and a user
    who says "stop following" must not have their command re-interpreted as a
    head motion by the chat planner.
    """
    t = text.strip()
    if not t:
        return None
    if _SAVE_POSE_RE.search(t):
        return "save_current_pose"
    if _CAPTURE_RE.search(t):
        return "capture_pose"
    if _PLAY_POSE_RE.search(t):
        return "play_pose"
    if _FOLLOW_START_RE.search(t):
        return "follow_start"
    if _FOLLOW_STOP_RE.search(t):
        return "follow_stop"
    return None


async def _send_status(websocket: WebSocket, payload: dict) -> None:
    try:
        await websocket.send_json(payload)
    except Exception as e:
        logger.debug(f"Status send failed: {e}")


async def try_handle_system_intent(
    text: str,
    websocket: WebSocket,
    save_dialog: SavePoseDialog,
    sim_only: bool | None = None,
    clean_logger: Any | None = None,
    intent_override: str | None = None,
    memory: HierarchicalMemory | None = None,
) -> bool:
    """If the text matches a follow/capture/save/play intent, dispatch and reply. Return True if handled.

    ``sim_only`` follows the same sim/hardware toggle as /move and the chat
    motion planner, so follow/capture never dispatch to the physical robot
    just because the server happens to be running in hardware mode.

    ``intent_override`` lets a caller that already ran the hybrid intent
    classifier (e.g. the WebSocket audio path) supply the exact immediate
    intent instead of re-running the regex matcher.

    ``memory`` is optional; when provided, every handled system-intent exchange
    is recorded so the LLM fallback sees the full conversation history,
    including turns that were handled by regex.
    """
    intent = intent_override
    if intent is None:
        intent = classify_system_intent(text)
    if intent is None:
        return False

    async def status_fn(payload: dict) -> None:
        await _send_status(websocket, payload)

    def _remember(response: str, waypoints: list[dict] | None = None) -> None:
        if memory is not None:
            memory.add_exchange(text, response, waypoints or [])

    if intent == "save_current_pose":
        joints = _get_robot_state()
        save_dialog.pending_joints = dict(joints)
        save_dialog.stage = _SaveStage.AWAITING_CONFIRM
        response = "I can save the current position. Should I go ahead?"
        await send_chat_response_with_audio(
            websocket,
            {
                "type": "chat_response",
                "role": "assistant",
                "content": response,
                "waypoints": [],
                "joint_states": _get_robot_state() or None,
            }
        )
        _remember(response)
        return True

    if intent == "play_pose":
        pose_name, all_names = _resolve_pose_name(text)
        if pose_name is None:
            if all_names:
                response = (
                    f"You have {len(all_names)} saved pose{'s' if len(all_names) > 1 else ''}: "
                    + ", ".join(all_names)
                    + '. Say "play" followed by a pose name to strike it.'
                )
            else:
                response = "You don't have any saved poses yet. Say 'save this pose' to make one."
            await send_chat_response_with_audio(
                websocket,
                {
                    "type": "chat_response",
                    "role": "assistant",
                    "content": response,
                    "waypoints": [],
                    "joint_states": _get_robot_state() or None,
                }
            )
            _remember(response)
            return True
        joints = get_pose(pose_name)
        if joints is None:
            response = f"I couldn't find the pose '{pose_name}'."
            await send_chat_response_with_audio(
                websocket,
                {
                    "type": "chat_response",
                    "role": "assistant",
                    "content": response,
                    "waypoints": [],
                    "joint_states": _get_robot_state() or None,
                }
            )
            _remember(response)
            return True
        await _execute_on_hardware_if_connected(joints)
        response = f"Playing your saved pose: {pose_name}."
        await send_chat_response_with_audio(
            websocket,
            {
                "type": "chat_response",
                "role": "assistant",
                "content": response,
                "waypoints": [],
                "joint_states": _get_robot_state() or None,
            }
        )
        _remember(response, waypoints=[{"joints": joints, "primitive": "execute_saved_pose"}])
        return True

    if intent == "library":
        all_names = list_pose_names()
        if all_names:
            response = (
                f"You have {len(all_names)} saved pose{'s' if len(all_names) > 1 else ''}: "
                + ", ".join(all_names)
                + '. Say "play" followed by a pose name to strike it.'
            )
        else:
            response = "You don't have any saved poses yet. Say 'save this pose' to make one."
        await send_chat_response_with_audio(
            websocket,
            {
                "type": "chat_response",
                "role": "assistant",
                "content": response,
                "waypoints": [],
                "joint_states": _get_robot_state() or None,
            }
        )
        _remember(response)
        return True

    if state.follow_controller is None:
        return False

    if intent == "follow_start":
        await state.follow_controller.start_follow(
            status_fn, sim_only=sim_only, clean_logger=clean_logger
        )
        response = "Following your movements — say stop when done."
        await send_chat_response_with_audio(
            websocket,
            {
                "type": "chat_response",
                "role": "assistant",
                "content": response,
                "waypoints": [],
                "joint_states": _get_robot_state() or None,
            }
        )
        _remember(response)
        return True

    if intent == "follow_stop":
        await state.follow_controller.stop_follow(
            status_fn, reason="user requested stop", clean_logger=clean_logger
        )
        response = "Stopped following."
        await send_chat_response_with_audio(
            websocket,
            {
                "type": "chat_response",
                "role": "assistant",
                "content": response,
                "waypoints": [],
                "joint_states": _get_robot_state() or None,
            }
        )
        _remember(response)
        return True

    if intent == "capture_pose":
        await state.follow_controller.trigger_capture_and_mimic(
            status_fn, sim_only=sim_only, clean_logger=clean_logger
        )
        response = "Capturing your pose — hold still for a few seconds."
        await send_chat_response_with_audio(
            websocket,
            {
                "type": "chat_response",
                "role": "assistant",
                "content": response,
                "waypoints": [],
                "joint_states": _get_robot_state() or None,
            }
        )
        _remember(response)
        return True

    return False
