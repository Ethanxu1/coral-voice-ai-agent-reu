# Pattern 1 — Fragmented Sequential Pose Tweaks

The user issues a chain of terse, one-clause commands. Each one is short on its own and only makes sense relative to the pose state left behind by the previous turn. This is the exact scenario DK described on Jun 24 ("raise head up" → "raise chin even higher" → "a little bit lower").

## Why kids talk like this

Young children rarely package a multi-step instruction into one well-formed sentence. They issue micro-corrections, watch the effect, then issue the next one — often without naming the joint or the direction again, because both are obvious *to them* from what just happened. The pronoun "it" and the adverbs "higher", "lower", "more" carry most of the meaning.

## Sample transcript

> **user** "raise your head up"

> **user** "raise your chin even higher"

> **user** "a little bit lower"

> **user** "more"

> **user** "okay stop, a tiny bit back up"

## Expected router output, turn by turn

Assume the head starts at `head_tilt: 0°` and the agent is in voice-only mode.

### Turn 1 — "raise your head up"

```json
{
  "verbal_response": "Tilting my head up.",
  "waypoints": [
    {
      "primitives": ["head_tilt"],
      "angle": null,
      "direction": "up",
      "speed": 1.0
    }
  ]
}
```

Resulting state: `head_tilt: 15°` (primitive default).

### Turn 2 — "raise your chin even higher"

`CURRENT_STATE` shows `head_tilt: 15.0`. "Chin" is a kid's word for the same joint (`head_tilt` in the up direction). "Even higher" is a relative adjustment with no specified delta.

```json
{
  "verbal_response": "Tilting up a bit more.",
  "waypoints": [
    {
      "primitives": ["head_tilt"],
      "angle": 25,
      "direction": "up",
      "speed": 1.0
    }
  ]
}
```

Resulting state: `head_tilt: 25°`.

### Turn 3 — "a little bit lower"

No joint named. The agent must infer from action history that the last-moved joint was `head_tilt`. "A little bit lower" inverts the direction relative to the prior motion.

```json
{
  "verbal_response": "Tilting back down a little.",
  "waypoints": [
    {
      "primitives": ["head_tilt"],
      "angle": 20,
      "direction": "up",
      "speed": 1.0
    }
  ]
}
```

Note: the primitive direction stays `up` — only the magnitude shrinks. The agent should NOT switch to `direction: down` for a small reduction within the same range.

### Turn 4 — "more"

Single word. Must resolve to "continue in the direction of the last delta," which was a downward adjustment.

```json
{
  "verbal_response": "Lowering more.",
  "waypoints": [
    {
      "primitives": ["head_tilt"],
      "angle": 15,
      "direction": "up",
      "speed": 1.0
    }
  ]
}
```

### Turn 5 — "okay stop, a tiny bit back up"

Compound utterance: "okay stop" is acknowledgement filler, "a tiny bit back up" is the actual instruction.

```json
{
  "verbal_response": "Going back up a tiny bit.",
  "waypoints": [
    {
      "primitives": ["head_tilt"],
      "angle": 18,
      "direction": "up",
      "speed": 1.0
    }
  ]
}
```

## Pass criteria

- All five turns produce non-empty waypoints — no clarification asks.
- The joint thread is continuous: every turn modifies `head_tilt`, never accidentally switches to `head_turn` or another head joint.
- "More" resolves in the same direction as the most recent delta, not the original raise. This requires the planner to read the *last delta* from action history, not just the last absolute position.
- "A tiny bit" produces a smaller magnitude change than "even higher" or unqualified "more." Concrete check: the magnitude of turn 5's delta should be ≤ the magnitude of turn 4's delta.

## Known failure modes today

1. **Default-angle override.** Pre-Jun 24 the planner sometimes treated `null` angles as "apply the default" even when an absolute value was already established, snapping back to 15° instead of nudging from the current value. Watch for this in turn 2.
2. **Direction flip on small decreases.** A naive planner sees "lower" and flips `direction` to `down`, which would push the head below neutral. Within the same primitive's range, "lower" should mean "smaller magnitude in the existing direction."
3. **"More" with no antecedent.** Without the last-delta lookup, "more" is genuinely ambiguous and the planner may ask for clarification. Pass requires it to use action history instead.
4. **Mid-term summary truncation.** Once the chain crosses the 6-exchange short-term window, the last-delta signal lives in mid-term summaries. The summary template must preserve direction-of-last-delta or this pattern breaks at turn 7+.

## What this exercises in the pipeline

- `src/coral_agent/prompts/router.md` — the "Relative angle adjustments" branch and the joint→primitive mapping table.
- `src/coral_agent/server.py` → `HierarchicalMemory` — short-term retention and mid-term summary fidelity.
- `src/coral_agent/state.py` — running joint state passed in as `CURRENT_STATE`.
