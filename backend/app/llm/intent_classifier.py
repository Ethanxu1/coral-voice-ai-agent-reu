"""Hybrid intent classifier for CORAL.

Regex/template matchers handle high-confidence, deterministic commands.
Anything ambiguous falls back to the LLM classifier, which is now constrained
by a strict Pydantic JSON schema.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langfuse import observe
from langfuse.openai import openai
from loguru import logger
from pydantic import TypeAdapter, ValidationError

from app.llm.config import LLM_MODEL
from app.llm.normalize_speech import normalize_for_regex
from app.schemas.intent import (
    ClarificationIntent,
    ConversationIntent,
    ImmediateIntent,
    Intent,
    MotionIntent,
)

PROMPTS_DIR = Path(__file__).parent / "prompts"

# Confidence thresholds. High-confidence regex results are returned directly;
# lower-confidence results are either clarified or sent to the LLM fallback.
HIGH_CONFIDENCE_THRESHOLD = float(os.getenv("INTENT_HIGH_CONFIDENCE_THRESHOLD", "0.85"))

# Per-category high-confidence gates.
_IMMEDIATE_HIGH_CONFIDENCE = 0.90
_MOTION_HIGH_CONFIDENCE = HIGH_CONFIDENCE_THRESHOLD
_CONVERSATION_HIGH_CONFIDENCE = 0.80

# Floor for a regex motion result to be worth a clarification question when the
# LLM fallback is unavailable.
_MOTION_LOW_CONFIDENCE = 0.55


@dataclass
class ClassifiedIntent:
    """Internal result from a single matcher."""

    type: str  # immediate, motion, clarification, conversation
    confidence: float
    data: dict[str, Any]
    reason: str

    def to_response(self) -> dict[str, Any]:
        """Convert to the response shape expected by /classify-intent."""
        return _classified_to_response(self)


def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


# ---------------------------------------------------------------------------
# Immediate / system commands
# ---------------------------------------------------------------------------

_IMMEDIATE_PATTERNS: list[tuple[re.Pattern[str], str, float]] = [
    (_compile(r"\b(follow me|mirror me|copy me|mimic me|start following|follow my moves|follow my movement|mirror my moves|copy my movements|mimic my movements)\b"), "follow_start", 0.95),
    (_compile(r"\b(stop following|stop mirroring|stop copying|don't follow me|stop mimicking|quit following)\b"), "follow_stop", 0.95),
    (_compile(r"\b(take a snapshot|take a picture|capture my pose|copy my pose|mimic my pose|snapshot|capture this|freeze|lock it in|record my pose|picture of me|take a picture of me|i want you to (take a picture|capture my pose|record my pose|copy my pose)|can you (take a picture|capture my pose|record my pose))\b"), "capture", 0.95),
    (_compile(r"\b(my poses|show poses|saved poses|list poses|what poses do i have|pose library)\b"), "library", 0.90),
    # "done" must be the whole message (or a known exit phrase) to avoid firing
    # on unrelated child speech like "I'm almost done".
    (_compile(r"^\s*(exit|quit|goodbye|bye|see you|i['’]m done|we['’]re done|that['’]s all|all done|done)[\s!.]*$"), "exit", 0.90),
    (_compile(r"\b(save this pose|save current position|save the current position|remember this pose|save it as is|save position|remember this|keep this pose|save the current pose)\b"), "save_robot_pose", 0.95),
]

_NAMING_PATTERNS: list[tuple[re.Pattern[str], float]] = [
    (_compile(r"\b(name this pose|call this)\s+['\"]?(.+?)['\"]?\s*$"), 0.95),
    (_compile(r"\b(save this as|remember this as)\s+['\"]?(.+?)['\"]?\s*$"), 0.90),
]

_UNDO_RESET_PATTERNS: list[tuple[re.Pattern[str], str, float]] = [
    (_compile(r"\b(undo|undo that|take it back|revert)\b"), "undo", 0.95),
    (_compile(r"\b(go back|step back|previous)\b"), "undo", 0.90),
    (_compile(r"\b(reset|start over|neutral|go to neutral|return to start)\b"), "reset", 0.95),
]


# ---------------------------------------------------------------------------
# Conversation patterns
# ---------------------------------------------------------------------------

_CONVERSATION_PATTERNS: list[re.Pattern[str]] = [
    _compile(r"^(hi|hello|hey|howdy|what['\u2019]s up)\b"),
    _compile(r"\b(how are you|what can you do|who are you|what is your name|tell me about yourself)\b"),
    _compile(r"\b(thanks?|thank you|that's cool|that['\u2019]s awesome|nice|great|wow|ok|okay)\b"),
    _compile(r"\b(what does that look like|describe your pose|what do you look like)\b"),
    _compile(r"^(yes|no|maybe)\b"),
]


# ---------------------------------------------------------------------------
# Motion command patterns
# ---------------------------------------------------------------------------

_SIDE_WORDS = r"(?P<side>left|right|both)"
_BODY_WORDS = r"(?P<body>arm|arms|elbow|elbows|head|hand|hands|forearm|forearms)"
_ANGLE_WORDS = r"(?P<angle>\d+)\s*(?:degrees?|deg)"
_RELATIVE_ANGLE_WORDS = r"(?P<rel>a little|a bit|a lot|more|less|slightly)"

_MOTION_PATTERNS: list[tuple[re.Pattern[str], str, float]] = [
    # Head turn
    (_compile(rf"\b(turn|look|move)\s+(?:your\s+)?head\s+(?P<dir>left|right)\b(?:\s+(?:to|by)\s+{_ANGLE_WORDS})?"), "head_turn", 0.92),
    # Head tilt (explicit head)
    (_compile(rf"\b(look|tilt|move)\s+(?:your\s+)?head\s+(?P<dir>up|down)\b(?:\s+(?:to|by)\s+{_ANGLE_WORDS})?"), "head_tilt", 0.92),
    # Head tilt (implicit: "look up", "look down")
    (_compile(r"\b(look|tilt)\s+(?P<dir>up|down)\b"), "head_tilt", 0.88),
    # Arm forward / raise (explicit direction)
    (_compile(rf"\b(raise|lift|move)\s+(?:your\s+)?{_SIDE_WORDS}?\s*(?:arm|arms)\s+(?P<dir>forward|up|out|sideways)\b(?:\s+(?:to|by)\s+{_ANGLE_WORDS})?"), "arm", 0.88),
    # Arm forward / raise (explicit side only)
    (_compile(rf"\b(raise|lift|move)\s+(?:your\s+)?{_SIDE_WORDS}\s+(?:arm|arms)\b(?:\s+(?:to|by)\s+{_ANGLE_WORDS})?"), "arm", 0.85),
    # Arm forward / raise (bare: "raise your arm" — ambiguous side, defaults to forward)
    (_compile(r"\b(raise|lift|move)\s+(?:your\s+)?(?:left|right|both)?\s*(?:arm|arms)\b"), "arm", 0.80),
    # Arm out / sideways
    (_compile(rf"\b(extend|put|move|hold)\s+(?:your\s+)?{_SIDE_WORDS}?\s*(?:arm|arms)\s+(?:out|to the side|sideways)\b(?:\s+(?:to|by)\s+{_ANGLE_WORDS})?"), "arm_out", 0.88),
    # Lower arm / put down
    (_compile(rf"\b(lower|put down|drop)\s+(?:your\s+)?{_SIDE_WORDS}?\s*(?:arm|arms)\b(?:\s+(?:to|by)\s+{_ANGLE_WORDS})?"), "arm_lower", 0.85),
    # Elbow bend
    (_compile(rf"\b(bend)\s+(?:your\s+)?{_SIDE_WORDS}?\s*(?:elbow|elbows)\b(?:\s+(?:to|by)\s+{_ANGLE_WORDS})?"), "elbow_bend", 0.88),
    (_compile(rf"\b(straighten|extend|unbend)\s+(?:your\s+)?{_SIDE_WORDS}?\s*(?:elbow|elbows)\b"), "elbow_straighten", 0.88),
    # Elbow / forearm rotation
    (_compile(rf"\b(rotate|twist)\s+(?:your\s+)?{_SIDE_WORDS}?\s*(?:forearm|forearms|elbow|elbows)\s+(?P<dir>in|out)\b(?:\s+(?:to|by)\s+{_ANGLE_WORDS})?"), "elbow_rotate", 0.90),
]

# Corrections are matched after motion patterns so that explicit body-part
# phrasing (e.g., "lower your right arm") is treated as a direct motion, while
# bare correction words ("lower", "faster") still adjust the last action.
# The "lower" pattern uses a negative lookahead to avoid swallowing arm_lower.
_LOWER_NEGATIVE_LOOKAHEAD = r"(?!\s+(?:your|my|the)?\s*(?:left|right|both)?\s*(?:arm|arms|elbow|elbows))"
_CORRECTION_PATTERNS: list[tuple[re.Pattern[str], str, float]] = [
    (_compile(r"\b(faster|speed up|quicker)\b"), "faster", 0.90),
    (_compile(r"\b(slower|slow down)\b"), "slower", 0.90),
    (_compile(r"\b(a little more|a bit more|more|higher|further|farther)\b"), "more", 0.85),
    (_compile(rf"\b(a little less|a bit less|less|lower|not that much|not so much|too much)\b{_LOWER_NEGATIVE_LOOKAHEAD}"), "less", 0.85),
]

_RETRY_PATTERNS: list[re.Pattern[str]] = [
    _compile(r"\b(try again|retry|redo|do it again|again|that['\u2019]s wrong|that was wrong|wrong|no,?(?: the)? other)\b"),
]


# ---------------------------------------------------------------------------
# Matcher helpers
# ---------------------------------------------------------------------------

def _has_assistant_history(history: list[dict] | None) -> bool:
    return bool(history and any(m.get("role") == "assistant" for m in history))


def _match_immediate(text: str) -> ClassifiedIntent | None:
    for pattern, intent, confidence in _IMMEDIATE_PATTERNS:
        if pattern.search(text):
            return ClassifiedIntent(
                type="immediate",
                confidence=confidence,
                data={"intent": intent},
                reason=f"High-confidence immediate pattern matched: {intent}",
            )

    for pattern, confidence in _NAMING_PATTERNS:
        match = pattern.search(text)
        if match:
            name = match.group(2).strip("\"'").strip()
            return ClassifiedIntent(
                type="immediate",
                confidence=confidence,
                data={"intent": "naming", "name": name},
                reason="High-confidence naming pattern matched",
            )

    for pattern, intent, confidence in _UNDO_RESET_PATTERNS:
        if pattern.search(text):
            return ClassifiedIntent(
                type="immediate",
                confidence=confidence,
                data={"intent": intent},
                reason=f"High-confidence undo/reset pattern matched: {intent}",
            )

    return None


def _match_conversation(text: str) -> ClassifiedIntent | None:
    for pattern in _CONVERSATION_PATTERNS:
        if pattern.search(text):
            return ClassifiedIntent(
                type="conversation",
                confidence=0.85,
                data={"text": text},
                reason="High-confidence conversational pattern matched",
            )
    return None


def _side_label(side: str | None) -> str:
    if not side:
        return ""
    side_lower = side.lower()
    if side_lower == "both":
        return "both"
    return side_lower


def _build_motion_description(match: re.Match[str], body_type: str) -> tuple[str, float]:
    """Build a kid-friendly description and confidence from a motion regex match."""
    side = _side_label(match.groupdict().get("side"))
    direction = match.groupdict().get("dir")
    angle = match.groupdict().get("angle")
    rel = match.groupdict().get("rel")
    verb = match.group(1).lower() if match.group(1) else "move"

    confidence = 0.90

    if body_type == "head_turn":
        if not direction:
            confidence -= 0.35
        desc = f"Turn head {direction or ''}".strip()
        if angle:
            desc += f" to {angle} degrees"
        elif rel:
            desc += f" {rel}"
        return desc, confidence

    if body_type == "head_tilt":
        if not direction:
            confidence -= 0.35
        desc = f"Tilt head {direction or ''}".strip()
        if angle:
            desc += f" to {angle} degrees"
        elif rel:
            desc += f" {rel}"
        return desc, confidence

    if body_type == "elbow_bend":
        if not side:
            confidence -= 0.40
        desc = f"Bend {side + ' ' if side else ''}elbow".strip()
        if angle:
            desc += f" to {angle} degrees"
        elif rel:
            desc += f" {rel}"
        return desc, confidence

    if body_type == "elbow_straighten":
        if not side:
            confidence -= 0.40
        return f"Straighten {side + ' ' if side else ''}elbow", confidence

    if body_type == "elbow_rotate":
        if not side:
            confidence -= 0.40
        if not direction:
            confidence -= 0.35
        desc = f"Rotate {side + ' ' if side else ''}forearm {direction or ''}".strip()
        if angle:
            desc += f" to {angle} degrees"
        return desc, confidence

    if body_type == "arm_lower":
        if not side:
            confidence -= 0.40
        return f"Lower {side + ' ' if side else ''}arm", confidence

    # arm / arm_out
    if body_type == "arm_out":
        if not side:
            confidence -= 0.40
        desc = f"Move {side + ' ' if side else ''}arm out to the side".strip()
        if angle:
            desc += f" to {angle} degrees"
        return desc, confidence

    # Generic arm raise/forward
    if not side:
        confidence -= 0.40
    if not direction:
        # If no direction, assume "forward/up" because "raise" implies that.
        direction = "forward"

    direction_label = direction
    if direction in {"up", "forward"}:
        direction_label = "forward and up"
    elif direction in {"out", "sideways"}:
        direction_label = "out to the side"

    if verb in {"raise", "lift"}:
        desc = f"Raise {side + ' ' if side else ''}arm {direction_label}".strip()
    else:
        desc = f"Move {side + ' ' if side else ''}arm {direction_label}".strip()

    if angle:
        desc += f" to {angle} degrees"
    return desc, confidence


def _match_motion(text: str) -> ClassifiedIntent | None:
    for pattern, body_type, base_confidence in _MOTION_PATTERNS:
        match = pattern.search(text)
        if match:
            description, conf = _build_motion_description(match, body_type)
            # Side-agnostic commands like "raise your arm" are under-specified.
            side = match.groupdict().get("side")
            if not side and "both" not in text and body_type not in {"head_turn", "head_tilt"}:
                conf = max(0.0, conf - 0.35)
            confidence = min(base_confidence, conf)
            return ClassifiedIntent(
                type="motion",
                confidence=confidence,
                data={"description": description},
                reason="Motion pattern matched",
            )
    return None


def _match_correction(text: str, history: list[dict] | None) -> ClassifiedIntent | None:
    """Corrections need a prior motion to make sense; otherwise treat as conversation."""
    has_history = _has_assistant_history(history)
    for pattern, correction_type, confidence in _CORRECTION_PATTERNS:
        if pattern.search(text):
            if not has_history:
                return ClassifiedIntent(
                    type="conversation",
                    confidence=0.80,
                    data={"text": text},
                    reason="Correction-like word with no motion history; treat as conversation",
                )
            return ClassifiedIntent(
                type="motion",
                confidence=confidence,
                data={"description": f"Adjust last action: {correction_type} ({text})"},
                reason=f"Correction pattern matched: {correction_type}",
            )
    return None


def _match_retry(text: str, history: list[dict] | None) -> ClassifiedIntent | None:
    """Retry/rollback patterns need prior motion context."""
    has_history = _has_assistant_history(history)
    for pattern in _RETRY_PATTERNS:
        if pattern.search(text):
            if not has_history:
                return ClassifiedIntent(
                    type="conversation",
                    confidence=0.80,
                    data={"text": text},
                    reason="Retry-like word with no motion history; treat as conversation",
                )
            return ClassifiedIntent(
                type="immediate",
                confidence=0.85,
                data={"intent": "rollback_and_retry"},
                reason="Retry pattern matched with history present",
            )
    return None


def _match_regex(text: str, history: list[dict] | None) -> ClassifiedIntent | None:
    """Run regex matchers in order of specificity. Return the best match."""
    normalized = normalize_for_regex(text)

    matchers = [
        _match_immediate,
        _match_retry,
        _match_motion,
        _match_correction,
        _match_conversation,
    ]
    for matcher in matchers:
        # retry/correction need history; the rest don't
        result = (
            matcher(normalized, history)
            if matcher in {_match_retry, _match_correction}
            else matcher(normalized)
        )
        if result is not None:
            logger.debug(
                f"Regex intent matched: {result.type} (confidence={result.confidence:.2f})"
            )
            return result
    return None


# ---------------------------------------------------------------------------
# Response conversion
# ---------------------------------------------------------------------------

_INTENT_ADAPTER = TypeAdapter(Intent)


def _classified_to_response(result: ClassifiedIntent) -> dict[str, Any]:
    """Convert a regex ClassifiedIntent into the validated API response dict."""
    payload: dict[str, Any] = {"type": result.type, "classifier": "regex", "reason": result.reason}
    data = result.data

    if result.type == "immediate":
        payload["intent"] = data["intent"]
        if data.get("name"):
            payload["name"] = data["name"]
    elif result.type == "motion":
        payload["description"] = data["description"]
    elif result.type == "clarification":
        payload["question"] = data["question"]
    elif result.type == "conversation":
        payload["text"] = data.get("text", "")

    # Validate once so the API contract is guaranteed.
    model = _INTENT_ADAPTER.validate_python(payload)
    return model.model_dump(mode="json")


def _threshold_for_type(intent_type: str) -> float:
    if intent_type == "immediate":
        return _IMMEDIATE_HIGH_CONFIDENCE
    if intent_type == "conversation":
        return _CONVERSATION_HIGH_CONFIDENCE
    return _MOTION_HIGH_CONFIDENCE


# ---------------------------------------------------------------------------
# LLM fallback
# ---------------------------------------------------------------------------

def _load_prompt() -> str:
    prompt_path = PROMPTS_DIR / "intent_classifier.md"
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8")
    return "You are an intent classifier for a voice-controlled robot. Respond with JSON only."


def _build_intent_json_schema() -> dict[str, Any]:
    """Build the JSON Schema used to constrain the LLM fallback output."""
    schema = _INTENT_ADAPTER.json_schema()
    # OpenAI structured outputs require a top-level object with additionalProperties false.
    schema["$schema"] = "http://json-schema.org/draft-07/schema#"
    schema["additionalProperties"] = False
    return schema


@observe(name="classify_intent_llm_fallback")
def _llm_classify(
    text: str,
    follow_active: bool,
    state_degrees: dict[str, float],
    state_description: str,
    saved_names: list[str],
    history: list[dict] | None,
    regex_result: ClassifiedIntent | None = None,
    model: str = LLM_MODEL,
) -> dict[str, Any]:
    """Fallback to the LLM classifier when regex confidence is too low."""
    system_prompt = _load_prompt()
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)

    saved_line = f"SAVED_POSES: {json.dumps(saved_names)}\n" if saved_names else ""
    messages.append({
        "role": "user",
        "content": (
            saved_line
            + f"CURRENT_STATE: {json.dumps(state_degrees)}\n"
            f"STATE_DESCRIPTION: {state_description}\n"
            f"follow_active: {str(follow_active).lower()}\n"
            f'Message: "{text}"'
        ),
    })

    response = openai.chat.completions.create(
        model=model,
        messages=messages,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "intent",
                "schema": _build_intent_json_schema(),
            },
        },
        max_completion_tokens=200,
    )
    content = response.choices[0].message.content or "{}"
    parsed = json.loads(content)
    parsed["classifier"] = "llm"
    reason = "LLM fallback"
    if regex_result is not None:
        reason += f" (regex {regex_result.type} confidence {regex_result.confidence:.2f})"
    parsed["reason"] = reason

    # Strict Pydantic validation guarantees the shape matches the API contract.
    intent_model = _INTENT_ADAPTER.validate_python(parsed)
    return intent_model.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_intent_regex(text: str, history: list[dict] | None = None) -> ClassifiedIntent | None:
    """Classify intent using regex/templates only.

    Returns None if no matcher fires, signaling the caller should fall back to
    the LLM.
    """
    result = _match_regex(text, history)
    if result is not None:
        logger.info(
            f"Regex classifier: type={result.type}, confidence={result.confidence:.2f}, "
            f"reason={result.reason}"
        )
    return result


def _clarification_from_regex(result: ClassifiedIntent) -> dict[str, Any]:
    description = result.data.get("description", "do that")
    return {
        "type": "clarification",
        "classifier": "regex",
        "reason": f"regex {result.type} low confidence ({result.confidence:.2f}); LLM failed",
        "question": f"Do you want me to {description.lower()}?",
    }


@observe(name="classify_intent_hybrid")
def classify_intent(
    text: str,
    follow_active: bool = False,
    state_degrees: dict[str, float] | None = None,
    state_description: str = "",
    saved_names: list[str] | None = None,
    history: list[dict] | None = None,
    model: str = LLM_MODEL,
) -> dict[str, Any]:
    """Hybrid classifier: regex first, then LLM fallback.

    Returns the same JSON shapes as the /classify-intent endpoint.
    """
    regex_result = classify_intent_regex(text, history=history)

    if regex_result is not None:
        threshold = _threshold_for_type(regex_result.type)
        if regex_result.confidence >= threshold:
            logger.info(
                f"Intent classified by regex: {regex_result.type} "
                f"(confidence={regex_result.confidence:.2f})"
            )
            return regex_result.to_response()

    # Regex either missed or is uncertain — ask the LLM.
    logger.info(
        "Regex confidence too low or no match; falling back to LLM"
        + (f" (best regex: {regex_result.type} @ {regex_result.confidence:.2f})" if regex_result else "")
    )

    try:
        return _llm_classify(
            text=text,
            follow_active=follow_active,
            state_degrees=state_degrees or {},
            state_description=state_description,
            saved_names=saved_names or [],
            history=history,
            regex_result=regex_result,
            model=model,
        )
    except (ValidationError, json.JSONDecodeError) as e:
        logger.warning(f"LLM returned invalid intent shape: {e}")
    except Exception as e:
        logger.error(f"LLM intent classification failed: {e}")

    # Final fallback: if regex had a low-confidence motion, use its description
    # as a clarification rather than failing open to conversation.
    if regex_result is not None:
        if regex_result.type == "motion" and regex_result.confidence >= _MOTION_LOW_CONFIDENCE:
            return _clarification_from_regex(regex_result)
        # For non-motion low-confidence results, return the regex result anyway
        # so the caller gets a best-effort answer instead of silence.
        return regex_result.to_response()

    return {
        "type": "conversation",
        "classifier": "llm",
        "reason": "No regex match; LLM failed",
        "text": text,
    }
