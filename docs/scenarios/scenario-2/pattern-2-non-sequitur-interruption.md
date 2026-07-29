# Pattern 2 — Non-Sequitur Interruption

The user is mid-task and abruptly switches topic — a question, an observation, or an unrelated comment — before returning to the original instruction (or not). This is the central case DK flagged on Jun 24: "two consecutive sentences may not have semantic relationship — they could be independent instructions."

## Why kids talk like this

Three-year-olds sustain a single conversational topic only about 20% of the time. Even older preschoolers shift focus rapidly when something else catches their attention. From the system's perspective, this looks like a *contextual discontinuity*: utterance N is about the robot's arm, utterance N+1 is about the user's pet hamster, utterance N+2 returns to the arm. The pipeline has to handle each as a standalone intent.

## Sample transcript

> **user** "lift your right arm up"

> **user** "do you have a name?"

> **user** "higher"

> **user** "I have a hamster"

> **user** "okay put your arm down now"

## Expected router output, turn by turn

Robot starts at neutral.

### Turn 1 — "lift your right arm up"

```json
{
  "verbal_response": "Lifting my right arm.",
  "waypoints": [
    {
      "primitives": ["right_arm_forward"],
      "angle": null,
      "direction": null,
      "speed": 1.0
    }
  ]
}
```

Resulting state: `r_sho_pitch: 90°`.

### Turn 2 — "do you have a name?"

No motion intent. The planner must recognize this as conversational, not pose-related, and respond verbally without emitting waypoints.

```json
{
  "verbal_response": "I'm CORAL! Want to keep working on the arm?",
  "waypoints": []
}
```

Critical: empty `waypoints` array, not a hallucinated motion. The `verbal_response` should optionally bridge back to the task context, but must not force the user to.

### Turn 3 — "higher"

Two turns since the last motion command, with an unrelated turn in between. The planner must still resolve "higher" against `r_sho_pitch: 90°` from turn 1 — the chit-chat turn must not have evicted that context.

```json
{
  "verbal_response": "Raising it higher.",
  "waypoints": [
    {
      "primitives": ["right_arm_forward"],
      "angle": 100,
      "direction": null,
      "speed": 1.0
    }
  ]
}
```

### Turn 4 — "I have a hamster"

Pure non-sequitur. No instruction. Same handling as turn 2.

```json
{
  "verbal_response": "Hamsters are cool!",
  "waypoints": []
}
```

### Turn 5 — "okay put your arm down now"

Resumes the task. "Put your arm down" with no delta means "set the joint that's raised back to 0" per `router.md` — same primitive that raised it, with `angle: 0`.

```json
{
  "verbal_response": "Putting my arm down.",
  "waypoints": [
    {
      "primitives": ["right_arm_forward"],
      "angle": 0,
      "direction": null,
      "speed": 1.0
    }
  ]
}
```

## Pass criteria

- Turns 2 and 4 produce **empty waypoints** with a friendly verbal acknowledgement. The robot must not move.
- Turn 3 ("higher") correctly threads back to `right_arm_forward` despite turn 2 being unrelated. The arm-disambiguation rule in `router.md` ("If a specific arm was last moved, assume the same arm") must survive the chit-chat turn.
- Turn 5's "put your arm down" maps to the *same* primitive that raised it (`right_arm_forward` at `angle: 0`), not to `neutral`. The router prompt explicitly calls this out — pass requires the planner to follow the rule even after non-sequiturs in the history.
- Action history rows are written only for motion turns (1, 3, 5), not for the chit-chat turns. Otherwise the "last moved" inference will break in longer conversations.

## Known failure modes today

1. **Hallucinated motion for chit-chat.** A planner unsure what to do with "do you have a name?" might emit a low-confidence waypoint, e.g. wiggle the head. This is the failure DK most wants to avoid.
2. **Topic-switch causes arm forgetting.** If short-term memory treats turn 2 as a full context entry, "higher" in turn 3 may lose its arm anchor and trigger a clarification ask.
3. **`neutral` collapse.** "Put your arm down" with two unrelated turns between it and the raise sometimes resolves to `neutral` — which moves *both* arms and the head — instead of just the right arm. The router prompt forbids this but the rule depends on the action-history lookup working.
4. **Verbal response context-blindness.** The verbal response to "I have a hamster" should be warm and short, not a clipped "I cannot help with that." Cold refusals break the interaction style required for a child user.

## Variant: silent non-sequitur

A subtler version of this pattern: the user mutters under their breath to themselves, e.g. "where did I put it…" — Whisper transcribes it because the mic is on, but it was not addressed to the robot. The pipeline currently has no way to detect this. Future work: an addressee-detection signal (e.g. eye gaze from the vision stream) so the planner can decide whether to respond at all.
