"""Pose Designer: talk a pose into shape by voice.

The child says what to change ("lift your right arm higher"); the LLM answers
with what it will do and a proposed change, which the page shows as a ghost
over the robot. Nothing moves until the child accepts. One LLM call per turn
both reads the child's intent (propose / accept / reject / done / chat) and
works out the change, so there is no regex classifier in front of it.

Changes are in "controls": one arm joint each, in degrees from the standing
rest, positive meaning the same thing on both arms (up, out, bent, swung out).
Arms only: the physical robot has no head servos, and leg changes can topple it.
"""

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Literal

from langfuse.openai import openai
from loguru import logger
from pydantic import BaseModel, Field, ValidationError

from app.config import LLM_MODEL
from app.llm.prompts import load_prompt
from app.robot.robot_params import JOINT_SAFE_RANGES
from app.robot.servo_config import STAND_PULSE, TICKS_PER_RAD

PULSES_PER_DEG = TICKS_PER_RAD * 3.141592653589793 / 180


@dataclass(frozen=True)
class Control:
    joint: str
    label: str
    # +1 if a positive change raises the servo pulse. Measured in the sim: every
    # control's positive direction lowers the left servo's pulse and raises the
    # right one's (tests/test_pose_design.py checks the hand moves the right way).
    sign: int


def _arm(side: str) -> dict[str, Control]:
    name = "left" if side == "l" else "right"
    sign = -1 if side == "l" else 1
    return {
        f"{name}_arm_forward": Control(f"{side}_sho_pitch", f"{name.title()} arm forward/up", sign),
        f"{name}_arm_out": Control(f"{side}_sho_roll", f"{name.title()} arm out to the side", sign),
        f"{name}_elbow_bend": Control(f"{side}_el_yaw", f"{name.title()} elbow bend", sign),
        f"{name}_forearm_out": Control(f"{side}_el_pitch", f"{name.title()} forearm swing out", sign),
    }


CONTROLS: dict[str, Control] = {**_arm("l"), **_arm("r")}
ControlName = Literal[tuple(CONTROLS)]  # type: ignore[valid-type]

Action = Literal["propose", "accept", "reject", "done", "chat"]


class Change(BaseModel):
    control: ControlName
    degrees: float = Field(ge=-180, le=180)


class DesignTurn(BaseModel):
    action: Action
    reply: str
    changes: list[Change]


FALLBACK_TURN = DesignTurn(
    action="chat", reply="Sorry, I didn't get that. Can you say it again?", changes=[]
)
# A proposal whose every change is past the end of a joint's range.
CANT_MOVE_REPLY = "I can't move that way any further. Try something else!"


def control_degrees(pulses: dict[str, int]) -> dict[str, float]:
    """Each control's angle in `pulses`, in degrees from the standing rest."""
    return {
        name: round(c.sign * (pulses.get(c.joint, STAND_PULSE[c.joint]) - STAND_PULSE[c.joint]) / PULSES_PER_DEG)
        for name, c in CONTROLS.items()
    }


def control_range(name: str) -> tuple[int, int]:
    """The degrees from the standing rest a control can reach (the joint's safe range)."""
    c = CONTROLS[name]
    ends = [c.sign * (p - STAND_PULSE[c.joint]) / PULSES_PER_DEG for p in JOINT_SAFE_RANGES[c.joint]]
    return round(min(ends)), round(max(ends))


def apply_changes(pulses: dict[str, int], changes: dict[str, float]) -> dict[str, int]:
    """`pulses` with each control moved by its change in degrees, kept in the joint's safe range."""
    out = dict(pulses)
    for name, degrees in changes.items():
        c = CONTROLS[name]
        lo, hi = JOINT_SAFE_RANGES[c.joint]
        start = pulses.get(c.joint, STAND_PULSE[c.joint])
        out[c.joint] = max(lo, min(hi, round(start + c.sign * degrees * PULSES_PER_DEG)))
    return out


def reachable_changes(pulses: dict[str, int], changes: dict[str, float]) -> dict[str, float]:
    """The part of `changes` the arms can really make from `pulses` (each joint
    stops at the end of its safe range); controls that can't move are left out."""
    before, after = control_degrees(pulses), control_degrees(apply_changes(pulses, changes))
    return {name: after[name] - before[name] for name in changes if after[name] != before[name]}


def merge_changes(changes: list[Change]) -> dict[str, float]:
    """Changes as {control: degrees}, summing any control named twice."""
    merged: dict[str, float] = {}
    for ch in changes:
        merged[ch.control] = merged.get(ch.control, 0) + ch.degrees
    return {name: deg for name, deg in merged.items() if round(deg) != 0}


# "Save this pose" while CORAL follows the child: regex only, so the pose is kept
# the moment it's said, with no LLM round trip. A verb that means keep it, with
# what to keep ("save it", "keep this one"), or on its own ("save!", "freeze!");
# never after a "don't"/"not".
_SAVE_VERB = r"(save|keep|remember|capture|freeze|lock|snap)"
_SAVE_RE = re.compile(
    rf"\b{_SAVE_VERB}\b(\s+(it|this|that|my|the|me))*\s*(\b(pose|position|one|in|now)\b|[.!?]*$)"
)
_NEGATED_RE = re.compile(r"\b(don'?t|do not|not|never|stop)\b")


def is_save_command(text: str) -> bool:
    """True if the child is telling CORAL to keep the pose it's in right now."""
    t = text.lower().strip()
    return bool(_SAVE_RE.search(t)) and not _NEGATED_RE.search(t)


# While CORAL is asleep, speech counts only with a wake word ("hey CORAL", alone
# or followed by the request), so background talk and noise aren't taken as
# instructions. Includes the names Whisper hears instead of "Coral".
_WAKE_RE = re.compile(
    r"\b(hey|hi|hello|okay|ok)\b[\s,.!?]*\b(coral|corral|carol|karol|carroll|choral|kora|cora)\b[\s,.!?]*"
)


def strip_wake_word(text: str) -> str | None:
    """What follows the wake word ("" if nothing does), or None if `text` has none."""
    m = _WAKE_RE.search(text.lower())
    return None if m is None else text[m.end():].strip().rstrip(".!?,").strip()


# An arm whose forward and out angles are both within this of 0 is hanging down.
HANGING_DEG = 10


def _turn_message(text: str, pulses: dict[str, int], proposal: dict[str, float]) -> str:
    now = control_degrees(pulses)
    lines = ["Current pose (degrees from standing rest; the range each control can reach):"]
    for name in CONTROLS:
        lo, hi = control_range(name)
        lines.append(f"- {name}: {now[name]} (range {lo} to {hi})")
    for side in ("left", "right"):
        if all(abs(now[f"{side}_arm_{d}"]) <= HANGING_DEG for d in ("forward", "out")):
            lines.append(f"Your {side} arm is hanging down, as low as it goes.")
    pending = ", ".join(f"{name} {deg:+g}" for name, deg in proposal.items()) or "none"
    lines.append(f"Proposed change waiting for an answer: {pending}")
    lines.append(f'Child said: "{text}"')
    return "\n".join(lines)


def _schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(Action.__args__)},
            "reply": {"type": "string"},
            "changes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "control": {"type": "string", "enum": list(CONTROLS)},
                        "degrees": {"type": "number"},
                    },
                    "required": ["control", "degrees"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["action", "reply", "changes"],
        "additionalProperties": False,
    }


async def design_turn(
    text: str,
    pulses: dict[str, int],
    proposal: dict[str, float],
    history: list[dict[str, str]],
) -> DesignTurn:
    """Ask the LLM what the child wants. Never raises: any LLM or parse
    failure becomes a "say that again" reply that changes nothing."""
    messages = [
        {"role": "system", "content": load_prompt("pose_design")},
        *history,
        {"role": "user", "content": _turn_message(text, pulses, proposal)},
    ]

    def call_llm() -> str:
        response = openai.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "pose_design_turn", "strict": True, "schema": _schema()},
            },
            max_completion_tokens=300,
        )
        return response.choices[0].message.content or "{}"

    try:
        return DesignTurn.model_validate(json.loads(await asyncio.to_thread(call_llm)))
    except (ValidationError, ValueError) as e:
        logger.warning(f"pose design: unusable LLM answer: {e}")
    except Exception as e:
        logger.warning(f"pose design: LLM call failed: {e}")
    return FALLBACK_TURN
