"""Intent Classifier LLM for two-stage robot control.

Stage 1 of the BrainBody architecture:
- Classifies user intent before passing to motion planner
- Always runs the LLM to classify intent (no keyword fast-path)
- Receives last 5 action sequences for context
- Generates a detailed router_prompt for the router agent
"""

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from langfuse import observe
from langfuse.openai import openai
from loguru import logger

from coral_agent.config import LLM_MODEL

PROMPTS_DIR = Path(__file__).parent / "prompts"


class IntentType(Enum):
    """Types of user intent."""

    MOTION_COMMAND = "motion_command"  # Normal motion request
    ROLLBACK_AND_RETRY = "rollback_and_retry"  # Undo and try again
    CORRECTION = "correction"  # Modify last action (faster, slower, etc.)
    UNDO = "undo"  # Just undo, no retry
    RESET = "reset"  # Reset to initial position
    CONVERSATION = "conversation"  # Chat, no motion needed


@dataclass
class IntentResult:
    """Result from intent classification."""

    intent_type: IntentType
    confidence: float
    reasoning: str = ""  # LLM's reasoning for the classification
    router_prompt: str | None = None  # Complete self-contained instruction for the router agent


def get_intent_prompt() -> str:
    """Load the intent classifier prompt from the markdown file."""
    prompt_path = PROMPTS_DIR / "intent.md"
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()


def format_action_sequences(action_sequences: list[dict]) -> str:
    """Format action sequences for inclusion in the intent classifier prompt.

    Most recent sequence is listed first so the LLM sees it immediately.
    """
    if not action_sequences:
        return "ACTION_SEQUENCES: (none - this is the first message)"

    lines = ["ACTION_SEQUENCES (MOST RECENT FIRST):"]
    for seq in reversed(action_sequences):
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
            lines.append(f'• "{user_req}" → [{wp_summary}]')
        else:
            lines.append(f'• "{user_req}" → [no motion]')

    return "\n".join(lines)


@observe(name="classify_intent")
def classify_intent(
    current_message: str,
    action_sequences: list[dict] | None = None,
    model: str = LLM_MODEL,
) -> IntentResult:
    """Classify the user's intent using an LLM and generate a router prompt.

    Args:
        current_message: The user's current message
        action_sequences: Last N action sequences from memory (each has user_request + waypoints list)
        model: OpenAI model to use for classification

    Returns:
        IntentResult with classified intent, reasoning, and router_prompt
    """
    sequences = action_sequences or []

    action_sequences_str = format_action_sequences(sequences)
    user_content = f"{action_sequences_str}\n\nCURRENT_MESSAGE: {current_message}"

    try:
        logger.debug(f"Classifying intent for: {current_message[:50]}...")

        system_prompt = get_intent_prompt()

        response = openai.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
            name="intent-classification",  # Langfuse generation name
        )

        content = response.choices[0].message.content
        logger.debug(f"Intent classifier response: {content[:100]}...")

        result = parse_intent_response(content, current_message, sequences)
        logger.info(
            f"Intent classified: {result.intent_type.value} "
            f"(confidence: {result.confidence:.2f})"
        )
        return result

    except Exception as e:
        logger.error(f"Intent classification error: {e}")
        return IntentResult(
            intent_type=IntentType.MOTION_COMMAND,
            confidence=0.5,
            reasoning=f"Fallback due to error: {e}",
            router_prompt=current_message,
        )


def parse_intent_response(
    content: str,
    current_message: str,
    action_sequences: list[dict],
) -> IntentResult:
    """Parse the LLM response into an IntentResult."""
    json_str = content.strip()

    # Handle markdown code blocks
    if "```json" in json_str:
        start = json_str.find("```json") + 7
        end = json_str.find("```", start)
        json_str = json_str[start:end].strip()
    elif "```" in json_str:
        start = json_str.find("```") + 3
        end = json_str.find("```", start)
        json_str = json_str[start:end].strip()

    try:
        data = json.loads(json_str)

        intent_type_str = data.get("intent_type", "motion_command")
        try:
            intent_type = IntentType(intent_type_str)
        except ValueError:
            intent_type = IntentType.MOTION_COMMAND

        return IntentResult(
            intent_type=intent_type,
            confidence=float(data.get("confidence", 0.8)),
            reasoning=data.get("reasoning", ""),
            router_prompt=data.get("router_prompt"),
        )

    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse intent JSON: {e}")
        return infer_intent_from_keywords(current_message, action_sequences)


def infer_intent_from_keywords(
    message: str, action_sequences: list[dict]
) -> IntentResult:
    """Fallback: infer intent from keywords if JSON parsing fails."""
    msg_lower = message.lower()

    last_user_request = action_sequences[-1].get("user_request") if action_sequences else None

    # Check for retry patterns
    retry_keywords = ["try again", "retry", "redo", "do it again", "again"]
    wrong_keywords = ["wrong", "incorrect", "not right", "that's not"]

    has_retry = any(kw in msg_lower for kw in retry_keywords)
    has_wrong = any(kw in msg_lower for kw in wrong_keywords)

    if has_retry or (has_wrong and last_user_request):
        return IntentResult(
            intent_type=IntentType.ROLLBACK_AND_RETRY,
            confidence=0.7,
            reasoning="Keyword fallback: detected retry/wrong keywords",
            router_prompt=(
                f"RETRY: The previous action was incorrect. "
                f"Try again: {last_user_request or message}"
            ),
        )

    # Check for undo patterns
    undo_keywords = ["undo", "go back", "revert", "back"]
    if any(kw in msg_lower for kw in undo_keywords):
        return IntentResult(
            intent_type=IntentType.UNDO,
            confidence=0.7,
            reasoning="Keyword fallback: detected undo keywords",
        )

    # Check for reset patterns
    reset_keywords = ["reset", "start over", "neutral", "beginning"]
    if any(kw in msg_lower for kw in reset_keywords):
        return IntentResult(
            intent_type=IntentType.RESET,
            confidence=0.7,
            reasoning="Keyword fallback: detected reset keywords",
        )

    # Check for correction patterns
    correction_keywords = ["faster", "slower", "more", "less", "too much", "not enough"]
    if any(kw in msg_lower for kw in correction_keywords):
        return IntentResult(
            intent_type=IntentType.CORRECTION,
            confidence=0.7,
            reasoning="Keyword fallback: detected correction keywords",
            router_prompt=f"Adjust the last action based on user feedback: {message}",
        )

    # Default to motion command
    return IntentResult(
        intent_type=IntentType.MOTION_COMMAND,
        confidence=0.6,
        reasoning="Keyword fallback: no special patterns detected",
        router_prompt=message,
    )
