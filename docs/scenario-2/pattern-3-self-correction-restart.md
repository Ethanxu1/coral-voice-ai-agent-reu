# Pattern 3 — Self-Correction and Mid-Utterance Restart

The user starts to give an instruction, realizes they meant something different partway through, and restarts within the same utterance. Whisper transcribes the whole thing — false start *and* correction — into a single text blob. The planner has to commit to the final intent without acting on the abandoned one.

## Why kids talk like this

Self-corrections, revisions, and false starts are typical disfluencies between roughly 2.5 and 5 years old, and persist with reduced frequency into early school age. They show up with no frustration or physical tension — the child simply re-aims mid-sentence. Common forms: a wrong word followed by "I mean" or "no", a wrong word silently corrected with the right one immediately after, or a full restart of the clause.

## Sample transcript

Each line is one Whisper output. Punctuation reflects Whisper's typical behavior — Whisper inserts commas at brief pauses and rarely uses ellipses.

> **user** "raise your left, no your right arm up"

> **user** "turn your head, um, the other way"

> **user** "bend your, wait, straighten your right elbow"

> **user** "lift both arms — no just the left one"

## Expected router output, turn by turn

Robot starts at neutral.

### Turn 1 — "raise your left, no your right arm up"

The "no" is the canonical restart marker. Final intent: right arm forward.

```json
{
  "verbal_response": "Raising my right arm.",
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

**Wrong output to watch for:** two waypoints, one per arm. The pipeline would actually try to raise the left arm first, then the right — visibly wrong to the child.

### Turn 2 — "turn your head, um, the other way"

"Um" is filler, no semantic content. "The other way" means: invert the direction of the most recent head turn. Since no head turn has happened yet, the planner should pick a default and confirm.

```json
{
  "verbal_response": "Which way — left or right?",
  "waypoints": []
}
```

This is the right behavior: "the other way" needs a referent. If a prior head turn existed, the planner should invert it; lacking one, ask.

### Turn 3 — "bend your, wait, straighten your right elbow"

"Wait" is a stronger restart cue than "no" or "um". Final intent: straighten (extend) the right elbow. Per `router.md`: "extend elbow" / "straighten elbow" → `*_elbow_bend` with `angle: 0`.

```json
{
  "verbal_response": "Straightening my right elbow.",
  "waypoints": [
    {
      "primitives": ["right_elbow_bend"],
      "angle": 0,
      "direction": null,
      "speed": 1.0
    }
  ]
}
```

If the elbow is already at 0, the waypoint is a no-op — that's fine. The pass criterion is that the planner does NOT bend it (which would happen if it took the first half of the sentence).

### Turn 4 — "lift both arms — no just the left one"

Dash transcribed by Whisper as a literal em-dash. "No" is the restart. Final intent: left arm only.

```json
{
  "verbal_response": "Lifting just my left arm.",
  "waypoints": [
    {
      "primitives": ["left_arm_forward"],
      "angle": null,
      "direction": null,
      "speed": 1.0
    }
  ]
}
```

## Pass criteria

- Each turn produces **exactly one logical intent**, not a sequence of two. No partial execution of the abandoned clause.
- The agent recognizes the cue tokens `no`, `wait`, `I mean`, `actually`, and `um` (when followed by a substantive correction) as restart markers, and ignores the pre-cue clause for motion planning.
- Filler-only utterances ("um", "uh", standalone "wait") produce **empty waypoints** and a short conversational acknowledgement.
- The verbal_response should reflect the *final* intent, not the abandoned one — i.e. it should not say "Raising my left and right arms" in turn 1.

## Known failure modes today

1. **Two-waypoint expansion.** The planner reads "raise left, raise right" as a sequence and emits a waypoint for each. The robot then visibly raises the wrong arm first before correcting. This is the dominant failure mode of unaugmented LLMs on this pattern.
2. **Verbal response leaks the false start.** Even when the waypoint is correct, the verbal_response sometimes says "Raising my left… I mean my right arm" — which sounds natural but is a small tell that the planner *almost* did the wrong thing. Acceptable for now; flag as a polish item.
3. **"The other way" with no referent.** Without a prior motion to invert, the planner may pick a random direction. Pass requires it to ask.
4. **Elbow direction confusion.** Turn 3's "straighten" maps to `angle: 0`, not to `direction: out`. The router prompt is clear about this but the rule is easy to lose under disfluency noise.

## Why this matters

In the Jun 24 Voice-Controlled Robotics in Early Education study, about 38% of voice commands from 4–6 year olds required repetition — most failures stemmed from the child being unable to formulate the instruction within the time window. Self-correction is the child's natural workaround: rather than re-prompt, they restart mid-utterance. A pipeline that handles this gracefully avoids forcing the child into the harder "repeat the whole thing cleanly" loop.

## What this exercises in the pipeline

- `src/coral_agent/prompts/router.md` — implicitly the chain-of-thought reasoning, which needs to handle disfluency cleanup before primitive selection. Consider adding an explicit example of `no`/`wait` handling to the prompt.
- Whisper transcription quality on `src/coral_agent/server.py` `transcribe_audio()` — Whisper's tendency to drop "um" and "uh" can either help (silently cleans the input) or hurt (loses the restart cue). Validate by checking actual Whisper output on a sample wav.
