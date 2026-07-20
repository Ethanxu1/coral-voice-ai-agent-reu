# CORAL Intent Classifier — Regex/Hybrid Matching

The intent classifier in `src/coral_agent/intent_classifier.py` uses a hybrid architecture:

1. **Regex/template matchers** run first and classify deterministic commands instantly.
2. If a matcher is uncertain (confidence below `INTENT_HIGH_CONFIDENCE_THRESHOLD`, default `0.85`), the classifier falls back to the LLM.
3. If the regex matchers find nothing, the LLM handles the message.

This gives the common, unambiguous commands (`"follow me"`, `"turn your head left"`, `"what can you do"`) a fast, reliable path while preserving the LLM for ambiguous or open-ended input.

## Entry point

```python
from coral_agent.intent_classifier import classify_intent

result = classify_intent(
    text="turn your head left",
    follow_active=False,
    state_degrees={...},
    state_description="...",
    saved_names=[...],
    history=[...],
)
```

Returned shapes match the `/classify-intent` endpoint. Every response also includes `classifier` (`"regex"` or `"llm"`) and a `reason` string so the UI can show which classifier handled the message and why:

```json
{"type": "immediate", "intent": "follow_start", "classifier": "regex", "reason": "High-confidence immediate pattern matched: follow_start"}
{"type": "motion", "description": "Turn head left", "classifier": "regex", "reason": "Motion pattern matched"}
{"type": "conversation", "text": "what can you do", "classifier": "regex", "reason": "High-confidence conversational pattern matched"}
{"type": "clarification", "question": "Which arm?", "classifier": "llm", "reason": "LLM fallback (regex motion confidence 0.15)"}
```

## Matcher order

Matchers run in order and return the first match:

1. Immediate / system commands
2. Retry / rollback
3. Corrections
4. Motion commands
5. Conversation patterns

If no matcher fires, the result is `None` and the LLM is called.

## 1. Immediate / system commands

These patterns are considered unambiguous and are returned at high confidence.

| Pattern | Intent | Confidence |
|---|---|---|
| `follow me`, `mirror me`, `copy me`, `start following`, `follow my moves` | `follow_start` | 0.95 |
| `stop following`, `stop mirroring`, `stop copying`, `don't follow me` | `follow_stop` | 0.95 |
| `take a snapshot`, `take a picture`, `capture my pose`, `copy my pose`, `mimic my pose`, `snapshot`, `capture this`, `freeze`, `lock it in` | `capture` | 0.95 |
| `my poses`, `show poses`, `saved poses`, `list poses`, `what poses do i have` | `library` | 0.90 |
| `exit`, `quit`, `goodbye`, `bye`, `see you`, `i'm done`, `we're done` | `exit` | 0.90 |
| `save this pose`, `save current position`, `save the current position`, `remember this pose`, `save it as is`, `save position` | `save_robot_pose` | 0.95 |
| `name this pose X`, `call this X`, `save this as X`, `remember this as X` | `naming` (with `name`) | 0.90–0.95 |
| `undo`, `undo that`, `take it back`, `revert` | `undo` | 0.95 |
| `go back`, `step back`, `previous` | `undo` | 0.90 |
| `reset`, `start over`, `neutral`, `go to neutral`, `return to start` | `reset` | 0.95 |

## 2. Retry / rollback

Regex matches phrases like `try again`, `retry`, `redo`, `do it again`, `again`, `that's wrong`, `that was wrong`, `wrong`, `no, the other`.

- If assistant history exists → `immediate` intent `rollback_and_retry` at 0.85.
- If no history exists → downgraded to `conversation` at 0.80, triggering LLM fallback.

This prevents a first utterance like "again" from being interpreted as a retry with nothing to retry.

## 3. Corrections

Regex matches `faster`, `slower`, `a little more`, `a bit more`, `more`, `higher`, `further`, `a little less`, `a bit less`, `less`, `lower`, `not that much`, `too much`.

- If assistant history exists → `motion` with confidence 0.85–0.90.
- If no history exists → `conversation` at 0.80, LLM fallback.

## 4. Motion commands

Motion regexes capture body part, side, direction, and optional angle.

| Body type | Example input | Output description |
|---|---|---|
| `head_turn` | `turn your head left` | "Turn head left" |
| `head_tilt` | `look up` | "Tilt head up" |
| `arm` | `raise your right arm forward` | "Raise right arm forward and up" |
| `arm_out` | `move your left arm out to the side` | "Move left arm out to the side" |
| `arm_lower` | `lower your right arm` | "Lower right arm" |
| `elbow_bend` | `bend your left elbow` | "Bend left elbow" |
| `elbow_straighten` | `straighten your right elbow` | "Straighten right elbow" |
| `elbow_rotate` | `rotate your left forearm in` | "Rotate left forearm in" |

### Confidence penalties

A match starts with a base confidence and is reduced for missing required information:

- Missing side on arm/elbow commands: −0.40
- Missing side on arm/elbow when the bare pattern matched: additional −0.35
- Missing direction on head turn/tilt: −0.35
- Missing direction on elbow rotate: −0.35

### Examples

| Input | Confidence | Result |
|---|---|---|
| `turn your head left` | 0.90 | Auto motion |
| `look up` | 0.88 | Auto motion |
| `raise your right arm` | 0.85 | Auto motion |
| `raise your arm` | ~0.15 | LLM fallback |
| `bend your elbow` | ~0.15 | LLM fallback |
| `turn your head` | ~0.55 | LLM fallback |

Explicit angles are captured and included in the description:

- `"raise your right arm to 45 degrees"` → `"Raise right arm forward and up to 45 degrees"`

## 5. Conversation patterns

Fires on greetings, questions, compliments, and meta phrases:

- `hi`, `hello`, `hey`, `howdy`
- `how are you`, `what can you do`, `who are you`, `what is your name`
- `thanks`, `thank you`, `that's cool`, `nice`, `great`, `wow`, `ok`, `okay`
- `what does that look like`, `describe your pose`, `what do you look like`
- bare `yes`, `no`, `maybe`

Returns `conversation` at 0.85 confidence.

## Confidence threshold

The environment variable `INTENT_HIGH_CONFIDENCE_THRESHOLD` controls how confident the regex result must be before it is returned directly. Default is `0.85`.

```bash
INTENT_HIGH_CONFIDENCE_THRESHOLD=0.9 python main.py
```

Raising the threshold makes the classifier more conservative and sends more input to the LLM. Lowering it makes more input take the fast regex path.

## LLM fallback

Regex falls back to the LLM when:

1. The best regex match has confidence below the threshold.
2. No regex matcher fires.
3. A correction or retry pattern matched but there is no assistant history.

The LLM receives the same prompt as before (`prompts/intent_classifier.md`) with `CURRENT_STATE`, `STATE_DESCRIPTION`, `follow_active`, saved poses, and conversation history.

If the LLM fails and regex had a low-confidence motion, the classifier emits a clarification question using the motion description instead of falling back to conversation. For example:

> "Do you want me to raise arm forward and up?"

## Extending matchers

To add a new immediate command, add a tuple to `_IMMEDIATE_PATTERNS`:

```python
(_compile(r"\b(my new command)\b"), "new_intent", 0.95),
```

To add a new motion pattern, add a tuple to `_MOTION_PATTERNS` and update `_build_motion_description` if the body type is new:

```python
(_compile(rf"\b(action)\s+(?:your\s+)?{_SIDE_WORDS}?\s*(?:body part)\b"), "body_type", 0.88),
```

Make sure confidence penalties are applied for any required missing fields so ambiguous variants reach the LLM.

## Routing in the Refined Demo

The intent classifier is the router: only finalized motion descriptions reach the motion planner.

| Classifier output | Frontend sends to `/ws` | Backend handler |
|---|---|---|
| `motion` | `{type: "chat", content: <raw>, intent_type: "motion", description: <clean description>}` | `process_chat_message` (motion planner) |
| `conversation` | `{type: "chat", content: <raw>, intent_type: "conversation"}` | `process_conversation_message` (chat LLM) |
| `immediate` | `{type: "chat", content: <raw>, intent_type: "immediate"}` | `try_handle_system_intent` |
| `clarification` | nothing — frontend asks the follow-up question and loops | — |

This means:
- "Move your arm up" → classified as `clarification` → no backend call until the user clarifies.
- "What can you do?" → classified as `conversation` → handled by `prompts/chat.md`, not the motion planner.
- "Raise your right arm" → classified as `motion` → approval modal → motion planner receives the clean description.

## Testing

Tests live in `tests/test_intent_classifier.py`. Run them with:

```bash
python -m pytest tests/test_intent_classifier.py -v
```

The tests cover immediate intents, undo/reset, motion commands with and without ambiguity, conversation patterns, corrections with/without history, retry with/without history, and no-match fallback.
