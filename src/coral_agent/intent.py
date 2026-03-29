"""Intent Classifier LLM for two-stage robot control.

Stage 1 of the BrainBody architecture:
- Classifies user intent before passing to motion planner
- Detects corrections, rollbacks, and retry requests semantically
- Extracts context for corrections (what was wrong, what to do differently)
"""

import json
import re
from dataclasses import dataclass
from enum import Enum

import ollama
from loguru import logger


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
    correction_context: str | None = None  # What was wrong and how to fix
    retry_instruction: str | None = None  # Rephrased instruction for retry
    original_request: str | None = None  # The original request being corrected
    reasoning: str = ""  # LLM's reasoning


def quick_intent_check(message: str, has_previous_action: bool) -> IntentResult | None:
    """Fast keyword-based intent detection for high-confidence patterns.

    This bypasses the LLM for common retry/undo patterns to ensure reliable detection.

    Args:
        message: The user's current message
        has_previous_action: Whether there was a previous action to retry/undo

    Returns:
        IntentResult if a high-confidence pattern matched, None to proceed to LLM
    """
    msg_lower = message.lower().strip()

    # Retry patterns - require previous action context
    retry_patterns = [
        r"^try\s+again",
        r"^retry$",
        r"^redo$",
        r"^again$",
        r"\bwrong\b",
        r"^do\s+it\s+again",
        r"^that'?s?\s+(not\s+)?right",
        r"^not\s+right",
        r"^incorrect",
    ]

    if has_previous_action:
        for pattern in retry_patterns:
            if re.search(pattern, msg_lower):
                return IntentResult(
                    intent_type=IntentType.ROLLBACK_AND_RETRY,
                    confidence=0.95,
                    reasoning=f"Fast-path: matched retry pattern '{pattern}'",
                )

    # Undo patterns - always check
    undo_patterns = [r"^undo$", r"^go\s+back$", r"^revert$"]
    for pattern in undo_patterns:
        if re.search(pattern, msg_lower):
            return IntentResult(
                intent_type=IntentType.UNDO,
                confidence=0.95,
                reasoning=f"Fast-path: matched undo pattern '{pattern}'",
            )

    # Reset patterns - always check
    reset_patterns = [r"^reset$", r"^start\s+over$", r"^go\s+to\s+neutral$"]
    for pattern in reset_patterns:
        if re.search(pattern, msg_lower):
            return IntentResult(
                intent_type=IntentType.RESET,
                confidence=0.95,
                reasoning=f"Fast-path: matched reset pattern '{pattern}'",
            )

    return None  # Proceed to LLM classification


INTENT_CLASSIFIER_PROMPT = """You are an intent classifier for a robot control system. Analyze the user's message and determine their intent.

## Context Provided:
- LAST_USER_REQUEST: The previous command the user gave
- LAST_ACTION: What the robot did in response
- CURRENT_MESSAGE: What the user just said

## Intent Types:
1. **motion_command**: User wants a NEW motion (not related to fixing previous action)
2. **rollback_and_retry**: User wants to UNDO the last action AND try it again differently
   - Examples: "no retry that", "that was wrong, try again", "do it again but correctly"
3. **correction**: User wants to MODIFY the current state (not undo, just adjust)
   - Examples: "faster", "slower", "a bit more", "too much", "not enough"
4. **undo**: User just wants to go back, no retry
   - Examples: "undo", "go back", "revert that"
5. **reset**: User wants to return to initial/neutral position
   - Examples: "reset", "start over", "go to neutral"
6. **conversation**: User is chatting, asking questions, not requesting motion
   - Examples: "hello", "what can you do?", "thanks"

## Output Format (JSON):
```json
{
  "intent_type": "motion_command|rollback_and_retry|correction|undo|reset|conversation",
  "confidence": 0.0-1.0,
  "reasoning": "Brief explanation of why this intent was chosen",
  "correction_context": "Only for rollback_and_retry/correction: what was wrong",
  "retry_instruction": "Only for rollback_and_retry: rephrased instruction that fixes the issue"
}
```

## Examples:

User says "no, that's wrong, try again" after robot moved arm wrong direction:
```json
{
  "intent_type": "rollback_and_retry",
  "confidence": 0.95,
  "reasoning": "User explicitly says 'wrong' and 'try again' - wants undo + retry",
  "correction_context": "Previous arm movement was in wrong direction",
  "retry_instruction": "Move the arm in the correct direction as originally requested"
}
```

User says "too fast, slower please" after robot moved:
```json
{
  "intent_type": "correction",
  "confidence": 0.9,
  "reasoning": "User wants speed adjustment, not a complete redo",
  "correction_context": "Movement was too fast, user wants slower speed"
}
```

User says "now raise your other arm":
```json
{
  "intent_type": "motion_command",
  "confidence": 0.95,
  "reasoning": "New motion request for a different arm, not a correction"
}
```

IMPORTANT: Output ONLY the JSON, no other text.
"""


def classify_intent(
    current_message: str,
    last_user_request: str | None = None,
    last_action_summary: str | None = None,
    model: str = "llama3.2",
) -> IntentResult:
    """Classify the user's intent using an LLM.

    Args:
        current_message: The user's current message
        last_user_request: The previous user request (if any)
        last_action_summary: Summary of what the robot did last (if any)
        model: Ollama model to use for classification

    Returns:
        IntentResult with classified intent and context
    """
    # Build context message
    context_parts = []
    if last_user_request:
        context_parts.append(f"LAST_USER_REQUEST: {last_user_request}")
    else:
        context_parts.append("LAST_USER_REQUEST: (none - this is the first message)")

    if last_action_summary:
        context_parts.append(f"LAST_ACTION: {last_action_summary}")
    else:
        context_parts.append("LAST_ACTION: (none - no previous action)")

    context_parts.append(f"CURRENT_MESSAGE: {current_message}")

    user_content = "\n".join(context_parts)

    try:
        logger.debug(f"Classifying intent for: {current_message[:50]}...")

        response = ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": INTENT_CLASSIFIER_PROMPT},
                {"role": "user", "content": user_content},
            ],
        )

        content = response["message"]["content"]
        logger.debug(f"Intent classifier response: {content[:100]}...")

        # Parse JSON response
        result = parse_intent_response(content, current_message, last_user_request)
        logger.info(
            f"Intent classified: {result.intent_type.value} "
            f"(confidence: {result.confidence:.2f})"
        )
        return result

    except ollama.ResponseError as e:
        logger.error(f"Ollama error in intent classifier: {e}")
        # Fall back to motion command on error
        return IntentResult(
            intent_type=IntentType.MOTION_COMMAND,
            confidence=0.5,
            reasoning=f"Fallback due to error: {e}",
        )
    except Exception as e:
        logger.error(f"Intent classification error: {e}")
        return IntentResult(
            intent_type=IntentType.MOTION_COMMAND,
            confidence=0.5,
            reasoning=f"Fallback due to error: {e}",
        )


def parse_intent_response(
    content: str,
    current_message: str,
    last_user_request: str | None,
) -> IntentResult:
    """Parse the LLM response into an IntentResult."""
    # Try to extract JSON from response
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
            correction_context=data.get("correction_context"),
            retry_instruction=data.get("retry_instruction"),
            original_request=last_user_request,
            reasoning=data.get("reasoning", ""),
        )

    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse intent JSON: {e}")
        # Try to infer intent from keywords as fallback
        return infer_intent_from_keywords(current_message, last_user_request)


def infer_intent_from_keywords(
    message: str, last_user_request: str | None
) -> IntentResult:
    """Fallback: infer intent from keywords if JSON parsing fails."""
    msg_lower = message.lower()

    # Check for retry patterns
    retry_keywords = ["try again", "retry", "redo", "do it again", "again"]
    wrong_keywords = ["wrong", "incorrect", "not right", "that's not"]

    has_retry = any(kw in msg_lower for kw in retry_keywords)
    has_wrong = any(kw in msg_lower for kw in wrong_keywords)

    if has_retry or (has_wrong and last_user_request):
        return IntentResult(
            intent_type=IntentType.ROLLBACK_AND_RETRY,
            confidence=0.7,
            correction_context="User indicated previous action was wrong",
            retry_instruction=last_user_request,
            original_request=last_user_request,
            reasoning="Keyword fallback: detected retry/wrong keywords",
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
            correction_context=f"User wants adjustment: {message}",
            reasoning="Keyword fallback: detected correction keywords",
        )

    # Default to motion command
    return IntentResult(
        intent_type=IntentType.MOTION_COMMAND,
        confidence=0.6,
        reasoning="Keyword fallback: no special patterns detected",
    )


def build_retry_context(
    intent: IntentResult,
    last_user_request: str,
    last_action_summary: str,
) -> str:
    """Build context message for retrying a failed action.

    This helps the motion planner understand what went wrong and try differently.
    """
    parts = [
        "## RETRY CONTEXT - Previous attempt failed",
        f"Original request: {last_user_request}",
        f"What robot did: {last_action_summary}",
    ]

    if intent.correction_context:
        parts.append(f"What was wrong: {intent.correction_context}")

    if intent.retry_instruction:
        parts.append(f"Retry instruction: {intent.retry_instruction}")
    else:
        parts.append(f"Please try again: {last_user_request}")

    parts.append(
        "\nIMPORTANT: The previous attempt was WRONG. "
        "Double-check your joint signs and values before outputting."
    )

    return "\n".join(parts)


def build_correction_context(
    intent: IntentResult,
    current_state: dict[str, float],
) -> str:
    """Build context message for a correction request."""
    parts = ["## CORRECTION REQUEST"]

    if intent.correction_context:
        parts.append(f"User feedback: {intent.correction_context}")

    parts.append("Adjust the current position based on the user's feedback.")
    parts.append("Do NOT redo the entire motion, just make the requested adjustment.")

    return "\n".join(parts)
