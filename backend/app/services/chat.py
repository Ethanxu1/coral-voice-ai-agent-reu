"""Chat / motion-planning message processing."""

from __future__ import annotations

import asyncio
import json
from typing import Awaitable, Callable

from langfuse import get_client, observe, propagate_attributes
from langfuse.openai import openai
from loguru import logger

from app.data.pose_db import get_pose, list_pose_names
from app.llm.config import LLM_MODEL
from app.llm.intent_classifier import classify_intent
from app.llm.primitives import (
    get_parameterized_primitive,
    get_primitive,
    resolve_primitive,
)
from app.robot.angle_utils import rad_to_servo_units
from app.robot.interface import ServoCommand
from app.robot.servo_config import SERVO_ID_MAP
from app.services.motion import (
    Waypoint,
    _get_robot_state,
    aggregate_safety,
    convert_state_to_degrees,
    dispatch_servo_commands,
    execute_parallel_tracks,
    execute_waypoints,
)
from app.services.recording import ConversationRecorder
from app.services.transcription import get_router_prompt, get_chat_prompt
from app.state import state
from app.state_manager import StateManager
from app.validation import (
    correct_motion_sign,
    describe_joint_state,
    validate_motion_sign,
    validate_waypoint,
)


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
            full_response = (
                f"{assistant_msg} [{joints_summary}]" if joints_summary else assistant_msg
            )
        else:
            full_response = assistant_msg

        self.short_term.append({"role": "assistant", "content": full_response})

        self.action_history.append(
            {
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
            }
        )

        if len(self.short_term) > self.short_term_limit * 2:
            old_user = self.short_term.pop(0)["content"]
            self.short_term.pop(0)
            self.mid_term_summaries.append(
                f"User asked: {old_user[:50]}... Robot responded with motion."
            )
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


def resolve_wp_entry(entry: dict) -> Waypoint | None:
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
    memory: HierarchicalMemory,
) -> tuple[dict, str, list]:
    robot_state = await asyncio.to_thread(_get_robot_state)
    state_description = describe_joint_state(robot_state)
    memory_context = memory.get_context_for_llm()
    return robot_state, state_description, memory_context


@observe(name="process_chat_message")
async def process_chat_message(
    user_message: str,
    memory: HierarchicalMemory,
    state_manager: StateManager,
    recorder: ConversationRecorder,
    simulator_instance: "AiNexSimulator | None",
    session_id: str,
    pre_context: tuple[dict, str, list] | None = None,
    on_action_started: Callable[[], Awaitable[None]] | None = None,
    sim_only: bool | None = None,
) -> dict:
    """Process a user message: single LLM call → primitive resolution → joint execution.

    ``on_action_started`` (if given) is awaited once, right before motion execution
    begins, but only when the plan actually contains a motion to run. It lets the
    caller tell the client "the robot is now moving" so a slow round-trip can be
    distinguished from a stall (the demo moves on instead of re-asking).
    """
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

        saved_names = list_pose_names()
        saved_line = f"SAVED_POSES: {json.dumps(saved_names)}\n" if saved_names else ""
        contextual_message = (
            saved_line
            + f"CURRENT_STATE: {json.dumps(convert_state_to_degrees(robot_state))}\n"
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
            logger.debug(
                f"LLM prompt tokens: {llm_response.usage.prompt_tokens} total, {cached} cached"
            )
            return llm_response.choices[0].message.content

        planner_response_text = await asyncio.to_thread(run_motion_planner)
        plan_data = json.loads(planner_response_text)

        response = plan_data.get("verbal_response", "")
        satisfied = plan_data.get("satisfied")

        # Handle execute_saved_pose action: look up stored joints and dispatch directly.
        if plan_data.get("action") == "execute_saved_pose":
            pose_name = plan_data.get("pose_name", "")
            joints = get_pose(pose_name)
            if joints is not None:
                if simulator_instance is not None:
                    state_manager.save_checkpoint(
                        simulator_instance, f"before:saved_pose:{pose_name}"
                    )
                cmds = [
                    ServoCommand(
                        servo_id=SERVO_ID_MAP[joint],
                        position=rad_to_servo_units(rad),
                        duration_ms=1000,
                    )
                    for joint, rad in joints.items()
                    if joint in SERVO_ID_MAP
                ]
                # Striking a named saved pose is a "demonstrate" action (same
                # category as /poses/play) — always reaches hardware once
                # connected, ignoring the composing-only sim_only toggle.
                await dispatch_servo_commands(cmds, sim_only=None)
                logger.info(f"Executed saved pose '{pose_name}' ({len(cmds)} joints)")
            else:
                logger.warning(f"Saved pose '{pose_name}' not found in database")
            memory.add_exchange(user_message, response, [])
            recorder.log_interaction(
                user_message=user_message,
                assistant_response=response,
                waypoints_extracted=[],
                waypoints_executed=[],
                router_response=plan_data,
            )
            return {
                "type": "chat_response",
                "role": "assistant",
                "content": response,
                "waypoints": [],
                "joint_states": _get_robot_state() or None,
                "satisfied": satisfied,
            }

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
                    # Auto-correct the most common LLM direction-sign mistakes so the
                    # demo behaves as the user expects, while still logging the issue.
                    corrected = correct_motion_sign(user_message, wp.joints)
                    if corrected != wp.joints:
                        logger.info(
                            f"Auto-corrected sign mismatch for '{user_message}': "
                            f"{wp.joints} → {corrected}"
                        )
                        wp.joints = corrected

            # Signal that a real motion is about to run, before the (potentially
            # slow) execution blocks. The client uses this to tell "already
            # executing" apart from "still thinking" if its own wait times out.
            if on_action_started is not None:
                await on_action_started()

            # Execute motion steps: batch consecutive Waypoints together so
            # sequential movements run in one tight interpolation loop (matching
            # original behavior), while parallel groups are dispatched with gather.
            idx = 0
            while idx < len(motion_steps):
                step = motion_steps[idx]
                if isinstance(step, list):
                    result = await execute_parallel_tracks(
                        simulator_instance, step, sim_only=sim_only
                    )
                    executed_waypoints.extend(result)
                    idx += 1
                else:
                    batch: list[Waypoint] = []
                    while idx < len(motion_steps) and not isinstance(motion_steps[idx], list):
                        batch.append(motion_steps[idx])
                        idx += 1
                    result = await execute_waypoints(simulator_instance, batch, sim_only=sim_only)
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
            "satisfied": satisfied,
        }

        # Only when a motion actually ran: the refined demo reports this verdict
        # to the user during pose fine-tuning, the same way it does for a
        # captured pose's /move. Absent means "no move, nothing to report".
        if executed_waypoints:
            response_data["safety"] = aggregate_safety(executed_waypoints)

        if validation_warnings:
            response_data["validation_warnings"] = validation_warnings

        if sign_warnings:
            response_data["sign_warnings"] = sign_warnings

        return response_data


@observe(name="process_conversation_message")
async def process_conversation_message(
    user_message: str,
    memory: HierarchicalMemory,
    recorder: ConversationRecorder,
    session_id: str,
) -> dict:
    """Handle a conversational message with the chat LLM, not the motion planner."""
    langfuse = get_client()

    with propagate_attributes(
        session_id=session_id,
        user_id="coral-user",
        tags=["coral-agent", "conversation"],
    ):
        langfuse.update_current_span(input=user_message)

        robot_state = _get_robot_state()
        state_description = describe_joint_state(robot_state)
        memory_ctx = memory.get_context_for_llm()

        saved_names = list_pose_names()
        saved_line = f"SAVED_POSES: {json.dumps(saved_names)}\n" if saved_names else ""
        contextual_message = (
            saved_line
            + f"CURRENT_STATE: {json.dumps(convert_state_to_degrees(robot_state))}\n"
            f"STATE_DESCRIPTION: {state_description}\n\n"
            f"USER_MESSAGE: {user_message}"
        )

        @observe(name="chat_llm")
        def run_chat_llm():
            prompt = get_chat_prompt()
            messages = [
                {"role": "system", "content": prompt},
                *memory_ctx,
                {"role": "user", "content": contextual_message},
            ]
            response = openai.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                response_format={"type": "json_object"},
                name="chat-response",
            )
            return response.choices[0].message.content

        response_text = await asyncio.to_thread(run_chat_llm)
        try:
            data = json.loads(response_text)
            response = data.get("verbal_response", "")
        except Exception:
            response = "I'm not sure what to say to that."

        memory.add_exchange(user_message, response, [])
        recorder.log_interaction(
            user_message=user_message,
            assistant_response=response,
            waypoints_extracted=[],
            waypoints_executed=[],
            router_response={"verbal_response": response},
        )

        result = {
            "type": "chat_response",
            "role": "assistant",
            "content": response,
            "waypoints": [],
            "joint_states": _get_robot_state() or None,
            "satisfied": None,
        }
        langfuse.update_current_span(output=result)
        return result
