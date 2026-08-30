"""Deterministic fallback motion planner for common child commands.

When the LLM structured output is missing, malformed, or produces no
resolvable primitives, this module maps canonical natural-language
descriptions (and many child paraphrases) directly to a `MotionPlan`.
"""

from __future__ import annotations

import re
from typing import Optional

from app.schemas.motion_plan import Direction, MotionPlan, PlainWaypoint, PrimitiveName


_ANGLE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:degrees?|deg|°)")
_SIDE_RE = re.compile(r"\b(left|right|both)\b")
_DIR_RE = re.compile(r"\b(left|right|up|down|in|out)\b")


def _extract_angle(text: str) -> Optional[float]:
    match = _ANGLE_RE.search(text)
    return float(match.group(1)) if match else None


def _extract_side(text: str) -> Optional[str]:
    match = _SIDE_RE.search(text)
    return match.group(1).lower() if match else None


def _extract_direction(text: str) -> Optional[Direction]:
    match = _DIR_RE.search(text)
    return match.group(1).lower() if match else None


def _side_prefix(side: str | None) -> str:
    if side == "both":
        return "both_"
    if side in {"left", "right"}:
        return f"{side}_"
    return ""


def _infer_primitive(description: str) -> Optional[PrimitiveName]:
    """Map a cleaned-up description to a single primitive name."""
    text = description.lower()
    side = _extract_side(text)
    direction = _extract_direction(text)
    side_p = _side_prefix(side)

    # Head. "look left/right" and "turn your head" both mean head_turn;
    # "look up/down" and "tilt your head" both mean head_tilt.
    if direction in {"left", "right"} and (
        "turn" in text or "look" in text or "face" in text
    ):
        return "head_turn"
    if direction in {"up", "down"} and (
        "tilt" in text or "look" in text or "nod" in text
    ):
        return "head_tilt"

    # Arms
    if "out" in text or "sideways" in text or "side" in text:
        if side == "both":
            return None  # handled separately below
        if side in {"left", "right"}:
            return f"{side_p}arm_out"  # type: ignore[return-value]
    if "lower" in text or "put down" in text or "drop" in text:
        if side == "both":
            return None
        if side in {"left", "right"}:
            return f"{side_p}arm_forward"  # type: ignore[return-value]
    if "raise" in text or "lift" in text or "move" in text or "extend" in text:
        if side == "both":
            return None
        if side in {"left", "right"}:
            return f"{side_p}arm_forward"  # type: ignore[return-value]

    # Elbows
    if "straighten" in text or "extend" in text or "unbend" in text:
        if side in {"left", "right"}:
            return f"{side_p}elbow_bend"  # type: ignore[return-value]
    if "bend" in text or "elbow" in text:
        if side in {"left", "right"}:
            return f"{side_p}elbow_bend"  # type: ignore[return-value]
    if "rotate" in text or "twist" in text:
        if side in {"left", "right"}:
            return f"{side_p}elbow_rotate"  # type: ignore[return-value]

    return None


def _build_plain(description: str) -> Optional[PlainWaypoint]:
    """Build a PlainWaypoint from a canonical description."""
    text = description.lower()
    side = _extract_side(text)
    direction = _extract_direction(text)
    angle = _extract_angle(text)

    primitives: list[PrimitiveName] = []

    # Both arms: create two single-side primitives.
    if side == "both" and ("arm" in text or "raise" in text or "lift" in text):
        if "out" in text or "sideways" in text or "side" in text:
            primitives = ["left_arm_out", "right_arm_out"]
        elif "lower" in text or "put down" in text or "drop" in text:
            primitives = ["left_arm_forward", "right_arm_forward"]
            angle = 0
        else:
            primitives = ["left_arm_forward", "right_arm_forward"]
        return PlainWaypoint(primitives=primitives, angle=angle)

    primitive = _infer_primitive(description)
    if primitive is None:
        return None

    # Straighten/lower/put down => target angle 0 unless the child said an
    # explicit angle.
    if angle is None and any(word in text for word in {"straighten", "lower", "put down", "drop", "extend"}):
        angle = 0

    return PlainWaypoint(primitives=[primitive], angle=angle, direction=direction)


def plan_for_description(description: str) -> Optional[MotionPlan]:
    """Return a deterministic MotionPlan for a known description, if any.

    Returns None when the description cannot be mapped safely.
    """
    waypoint = _build_plain(description)
    if waypoint is None:
        return None
    return MotionPlan(action="motion", waypoints=[waypoint])


def plan_for_saved_pose(pose_name: str) -> MotionPlan:
    """Return the execute_saved_pose plan for a named saved pose."""
    return MotionPlan(
        action="execute_saved_pose",
        pose_name=pose_name,
        verbal_response=f"Executing your saved pose '{pose_name}'.",
    )
