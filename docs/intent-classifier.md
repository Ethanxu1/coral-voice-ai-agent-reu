# CORAL Intent Classifier — Regex/Hybrid Matching

The intent classifier in [`src/llm/intent_classifier.py`](../src/llm/intent_classifier.py) uses a hybrid architecture:

1. **Regex/template matchers** run first and classify deterministic commands instantly.
2. If a matcher is uncertain (confidence below `INTENT_HIGH_CONFIDENCE_THRESHOLD`, default `0.85`), the classifier falls back to the LLM.
3. If the regex matchers find nothing, the LLM handles the message.

This gives the common, unambiguous commands (`"follow me"`, `"turn your head left"`, `"what can you do"`) a fast, reliable path while preserving the LLM for ambiguous or open-ended input.

The classifier sits between transcription and the motion planner — see [code-flow.md](code-flow.md) for the full voice-to-motion path, and [overview.md](overview.md) for how the pieces fit together. The fallback model is `LLM_MODEL` from [`src/llm/config.py`](../src/llm/config.py), overridable per call via the `model` argument.

## Entry point

```python
from llm.intent_classifier import classify_intent

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
| `follow me`, `mirror me`, `copy me`, `mimic me`, `start following`, `follow my moves`, `follow my movement`, `mirror my moves`, `copy my movements`, `mimic my movements` | `follow_start` | 0.95 |
| `stop following`, `stop mirroring`, `stop copying`, `don't follow me`, `stop mimicking`, `quit following` | `follow_stop` | 0.95 |
| `take a snapshot`, `take a picture`, `capture my pose`, `copy my pose`, `mimic my pose`, `snapshot`, `capture this`, `freeze`, `lock it in`, `record my pose`, `picture of me`, `take a picture of me`, plus `"i want you to..."` / `"can you..."` wrappers around take a picture/capture my pose/record my pose/copy my pose | `capture` | 0.95 |
| `my poses`, `show poses`, `saved poses`, `list poses`, `what poses do i have`, `pose library` | `library` | 0.90 |
| `exit`, `quit`, `goodbye`, `bye`, `see you`, `i'm done`, `we're done`, `that's all`, `all done`, `done` | `exit` | 0.90 |
| `save this pose`, `save current position`, `save the current position`, `remember this pose`, `save it as is`, `save position`, `remember this`, `keep this pose`, `save the current pose` | `save_robot_pose` | 0.95 |
| `name this pose X`, `call this X` | `naming` (with `name`) | 0.95 |
| `save this as X`, `remember this as X` | `naming` (with `name`) | 0.90 |
| `undo`, `undo that`, `take it back`, `revert` | `undo` | 0.95 |
| `go back`, `step back`, `previous` | `undo` | 0.90 |
| `reset`, `start over`, `neutral`, `go to neutral`, `return to start` | `reset` | 0.95 |

Note: the `exit` pattern matches the bare word `done` anywhere in the message, not just phrases like "i'm done" — e.g. "done" on its own also fires it.

## 2. Retry / rollback

Regex matches phrases like `try again`, `retry`, `redo`, `do it again`, `again`, `that's wrong`, `that was wrong`, `wrong`, `no, the other`.

- If assistant history exists → `immediate` intent `rollback_and_retry` at 0.85.
- If no history exists → downgraded to `conversation` at 0.80, triggering LLM fallback.

This prevents a first utterance like "again" from being interpreted as a retry with nothing to retry.

## 3. Corrections

Regex matches `faster`, `speed up`, `quicker`, `slower`, `slow down`, `a little more`, `a bit more`, `more`, `higher`, `further`, `farther`, `a little less`, `a bit less`, `less`, `lower`, `not that much`, `not so much`, `too much`.

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
| `arm_lower` | `put down your right arm` | "Lower right arm" |
| `elbow_bend` | `bend your left elbow` | "Bend left elbow" |
| `elbow_straighten` | `straighten your right elbow` | "Straighten right elbow" |
| `elbow_rotate` | `rotate your left forearm in` | "Rotate left forearm in" |

Note: `lower` is also a correction keyword (§3), and the corrections matcher runs before the motion matcher. So a phrase built around the bare word "lower" — e.g. `"lower your right arm"` — never reaches the `arm_lower` matcher: with no assistant history it's classified as `conversation`, and with history it's classified as a correction (`"Adjust last action: less (lower your right arm)"`), not `"Lower right arm"`. Only `put down`/`drop` phrasing reliably reaches `arm_lower`.

### Confidence penalties

A match starts with a base confidence of 0.90 and is reduced for missing required information:

- Missing side on arm/elbow commands (`arm`, `arm_out`, `arm_lower`, `elbow_bend`, `elbow_straighten`, `elbow_rotate`): −0.40, plus an additional −0.35 applied afterward for the same missing side. In practice these two penalties always fire together (there's no code path that gives just one), so any arm/elbow command with an unspecified side lands around 0.15 confidence regardless of the pattern's base confidence — enough to trigger LLM fallback every time.
- `head_turn`, `head_tilt`, and `elbow_rotate` patterns require their direction word (`left`/`right`, `up`/`down`, `in`/`out`) to match at all — the regex has no optional form. So a direction-less phrase like `"turn your head"` or `"rotate your forearm"` doesn't produce a low-confidence motion result; it simply doesn't match any motion pattern, and falls through to the conversation matcher or a full LLM classification instead.

### Examples

| Input | Confidence | Result |
|---|---|---|
| `turn your head left` | 0.90 | Auto motion |
| `look up` | 0.88 | Auto motion |
| `raise your right arm` | 0.85 | Auto motion |
| `raise your arm` | ~0.15 | LLM fallback |
| `bend your elbow` | ~0.15 | LLM fallback |
| `turn your head` | no match (direction required) | Falls through regex entirely; handled by the LLM from scratch |

Explicit angles are captured and included in the description:

- `"raise your right arm to 45 degrees"` → `"Raise right arm forward and up to 45 degrees"`

`_build_motion_description` has logic to append a relative modifier (`a little`, `a bit`, `a lot`, `more`, `less`, `slightly`) when no explicit angle is present, for head turn, head tilt, and elbow bend — but none of the compiled `_MOTION_PATTERNS` regexes actually capture a `rel` group, so this path is currently dead code. In practice trailing modifiers are dropped from the description:

- `"turn your head left a little"` → `"Turn head left"` (not `"Turn head left a little"`)

Two defaults worth knowing: a bare arm command with no direction assumes forward/up (because "raise" implies it), and `both` counts as a specified side, so `"raise both arms"` does not take the missing-side penalty.

## 5. Conversation patterns

Fires on greetings, questions, compliments, and meta phrases:

- `hi`, `hello`, `hey`, `howdy`, `what's up` (must be at the start of the message)
- `how are you`, `what can you do`, `who are you`, `what is your name`, `tell me about yourself`
- `thanks`, `thank you`, `that's cool`, `that's awesome`, `nice`, `great`, `wow`, `ok`, `okay`
- `what does that look like`, `describe your pose`, `what do you look like`
- bare `yes`, `no`, `maybe` (must be at the start of the message)

Returns `conversation` at 0.85 confidence.

## Confidence threshold

The environment variable `INTENT_HIGH_CONFIDENCE_THRESHOLD` controls how confident the regex result must be before it is returned directly. Default is `0.85`.

```bash
INTENT_HIGH_CONFIDENCE_THRESHOLD=0.9 uv run server
```

Raising the threshold makes the classifier more conservative and sends more input to the LLM. Lowering it makes more input take the fast regex path.

## LLM fallback

Regex falls back to the LLM when:

1. The best regex match has confidence below the threshold.
2. No regex matcher fires.
3. A correction or retry pattern matched but there is no assistant history.

The LLM receives the same prompt as before ([`src/llm/prompts/intent_classifier.md`](../src/llm/prompts/intent_classifier.md)) with `CURRENT_STATE`, `STATE_DESCRIPTION`, `follow_active`, saved poses, and conversation history.

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
| `motion` | `{type: "chat", content: <raw>, intent_type: "motion", description: <clean description>, sim_only: <bool>}` | `process_chat_message` (motion planner) |
| `conversation` | `{type: "chat", content: <raw>, intent_type: "conversation"}` | `process_conversation_message` (chat LLM) |
| `immediate` | `{type: "chat", content: <raw>, intent_type: "immediate"}` | `try_handle_system_intent` |
| `clarification` | nothing — frontend asks the follow-up question and loops | — |

This means:
- "Move your arm up" → classified as `clarification` → no backend call until the user clarifies.
- "What can you do?" → classified as `conversation` → handled by [`src/llm/prompts/chat.md`](../src/llm/prompts/chat.md), not the motion planner.
- "Raise your right arm" → classified as `motion` → approval modal → motion planner receives the clean description.

## Testing

Tests live in `tests/test_intent_classifier.py`. Run them with:

```bash
uv run pytest tests/test_intent_classifier.py -v
```

The tests cover immediate intents, undo/reset, motion commands with and without ambiguity, conversation patterns, corrections with/without history, retry with/without history, no-match fallback, and that a regex response includes the `classifier`/`reason` metadata fields.
