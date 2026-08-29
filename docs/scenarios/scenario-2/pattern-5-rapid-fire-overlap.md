# Pattern 5 — Rapid-Fire and Overlapping Commands

The user fires off multiple instructions in quick succession, sometimes within a single utterance, sometimes as a burst of utterances that arrive faster than the agent can execute the previous one. This stresses both the *parsing* side (one utterance → many waypoints) and the *concurrency* side (later utterance arrives mid-execution and may supersede the earlier).

## Why kids talk like this

When a child is excited, the speech rate goes up and the per-utterance content density goes down: shorter clauses, more of them, fewer pauses. This is the same population where disfluencies are most likely to cluster — excitement and rushed speech are explicitly named in the developmental literature as triggers. Add the natural impulse to "stack up" ideas before they're forgotten and you get bursts like "shake your head and raise your arm and look up and wave!"

## Sample transcript

> **user** "shake your head and raise your right arm and look up"

> **user** "wave! wave! wave!"

> **user** *(during execution of the previous turn)* "actually stop waving and bend your elbow"

> **user** "okay now arm down arm out arm up"

## Expected router output, turn by turn

Robot starts at neutral.

### Turn 1 — "shake your head and raise your right arm and look up"

Three intents in one utterance, naturally chunked by "and." Two of the three (`head_turn` for shake, `right_arm_forward` for raise) can run in parallel because they operate on disjoint joints. The third (`head_tilt` for look up) shares the `head` joint cluster with the shake — so it must serialize after.

Per `router.md`'s parallel-track rule, multiple primitives in one waypoint must use disjoint joints. So this becomes two waypoints:

```json
{
  "verbal_response": "Shaking my head, raising my right arm, then looking up.",
  "waypoints": [
    {
      "primitives": ["head_turn", "right_arm_forward"],
      "angle": null,
      "direction": "left",
      "speed": 1.5
    },
    {
      "primitives": ["head_tilt"],
      "angle": null,
      "direction": "up",
      "speed": 1.0
    }
  ]
}
```

Note: "shake your head" is a stylized motion the router prompt doesn't include as a single primitive. A reasonable approximation is one `head_turn` to one side; a more complete one would alternate sides, but that would consume more waypoints. Start with the single turn and tune later.

### Turn 2 — "wave! wave! wave!"

Repetition for emphasis, not a request for three waves. Map to one wave gesture. "Wave" is currently a manual `command` rather than a primitive — the planner should either emit the underlying primitive composition or treat "wave" as an alias.

```json
{
  "verbal_response": "Waving hi!",
  "waypoints": [
    {
      "primitives": ["right_arm_forward"],
      "angle": 90,
      "direction": null,
      "speed": 2.0
    },
    {
      "primitives": ["right_elbow_bend"],
      "angle": 45,
      "direction": null,
      "speed": 2.5
    },
    {
      "primitives": ["right_elbow_bend"],
      "angle": 0,
      "direction": null,
      "speed": 2.5
    },
    {
      "primitives": ["right_elbow_bend"],
      "angle": 45,
      "direction": null,
      "speed": 2.5
    },
    {
      "primitives": ["right_elbow_bend"],
      "angle": 0,
      "direction": null,
      "speed": 2.5
    }
  ]
}
```

### Turn 3 — superseding interrupt during execution

This is the distributed-input case from `scenario-1/voice-only-feedback-loop.md` §4, but originating from natural child speech rather than a contrived test. The waypoint queue from turn 2 is mid-execution when this arrives:

> **user** "actually stop waving and bend your elbow"

Today's pipeline serializes — turn 3 waits for turn 2 to finish, then runs. The right behavior is:

1. Cancel the remaining waypoints in turn 2's queue.
2. Snap to a settled position (current interpolation target).
3. Then execute turn 3.

```json
{
  "verbal_response": "Okay, stopping. Bending my right elbow.",
  "waypoints": [
    {
      "primitives": ["right_elbow_bend"],
      "angle": 90,
      "direction": null,
      "speed": 1.0
    }
  ]
}
```

This requires a `RobotController.abort()` hook that does not exist today (flagged in `scenario-1/vision-voice-feedback-loop.md` §5 as well). Until then, the pass criterion is *correctness after serialization*: turn 3 runs faithfully after turn 2 finishes, even if the user's "stop" is delayed.

### Turn 4 — "okay now arm down arm out arm up"

Three sequential commands on the same arm, no conjunctions. Sequencing implied by order: down → out → up. All three target the same arm and the same joint cluster, so they must serialize.

`CURRENT_STATE` shows `r_sho_pitch: 90°`, `r_el_yaw: -90°` from the wave. "Arm" with no side specified inherits "right" from history.

```json
{
  "verbal_response": "Arm down, out, then up.",
  "waypoints": [
    {
      "primitives": ["right_arm_forward"],
      "angle": 0,
      "direction": null,
      "speed": 1.5
    },
    {
      "primitives": ["right_arm_out"],
      "angle": 90,
      "direction": null,
      "speed": 1.5
    },
    {
      "primitives": ["right_arm_forward"],
      "angle": 90,
      "direction": null,
      "speed": 1.5
    }
  ]
}
```

Note: "arm out" before "arm up" requires returning to neutral on `right_arm_forward` first, then raising `right_arm_out`, then re-raising `right_arm_forward`. The planner needs to recognize that `right_arm_out` and `right_arm_forward` operate on different shoulder axes and can't be skipped between.

## Pass criteria

- **One utterance → multiple waypoints** correctly decomposed. Turn 1 must produce 2 waypoints, not 1 (which would crash on joint conflict) and not 3 (which would waste a turn on the head clustering).
- **Parallel where possible, serial where required.** Disjoint-joint commands packed into one waypoint per the router prompt's rule; conflicting commands serialized.
- **Repetition collapsed.** "Wave wave wave" → one wave. Quantity escalators ("a lot", "really high") increase amplitude, not waypoint count.
- **Implicit arm inheritance.** Turn 4's "arm" with no side resolves to the arm last moved (right), per the `router.md` disambiguation rule.
- **Speed reflects energy.** Excited-sounding bursts should bump `speed` up (≥1.5) so the motion matches the user's affect. This is a polish criterion, not a correctness one.

## Known failure modes today

1. **One-waypoint joint conflict.** Naive planner packs all three of turn 1's primitives into a single waypoint, which collides on the `head` joint cluster. The validator should catch this, but the planner shouldn't generate it.
2. **N-times expansion of repetition.** "Wave wave wave" becomes three waves back to back, doubling latency. The planner needs to read the repetition as emphasis.
3. **Mid-execution interrupt ignored.** Turn 3 today is queued until turn 2 completes (~3 seconds of waving). The user sees their "stop" command ignored for several seconds — a critical UX failure.
4. **Sequential commands run in wrong order.** Turn 4's "down out up" depends on order preservation. A planner that re-sorts by joint name or by execution efficiency will break the user's intent.
5. **Speed flatlines at 1.0.** A planner that always uses speed 1.0 makes excited bursts look uninterested. This is a soft failure but matters for child engagement.

## What this exercises in the pipeline

- `backend/app/llm/prompts/router.md` — the parallel-track rule, the disambiguation rule, and the speed conventions.
- `backend/app/services/chat.py` `process_chat_message()` — concurrency model. Today this is strictly serial; the pattern motivates an `abort()` hook on `RobotController`.
- `backend/app/robot/sim_controller.py` and `hardware_controller.py` — both need a cancellation path if turn-3-style interrupts are to be handled in real time.

## Open question

Should consecutive overlapping commands from the same user be **merged** ("shake head and wave" → one fused composite) or **queued** (back-to-back waypoints)? Merging keeps latency down but loses the user's pacing; queuing preserves intent but compounds delay. Worth measuring with real child users before committing to one.
