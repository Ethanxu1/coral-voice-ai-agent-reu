# Pattern 4 — Imaginative and Impossible Requests

The user issues a request that has no direct mapping to the primitive library, usually because it's framed inside a pretend-play scenario or asks for a physically impossible action. "Be a dinosaur." "Fly!" "Do a backflip." "Pretend you're swimming."

## Why kids talk like this

Children up to roughly 8 years old anthropomorphize robots strongly — many treat the robot as something between a peer, a pet, and a stuffed animal. Pretend play, which peaks around ages 3–7, naturally extends to anything in the room, including a humanoid robot. The Child Mind Institute notes that pretend play is how children "express creativity and develop social and emotional skills" — so when a child says "be a dinosaur," it is not a misunderstanding of the robot's capabilities, it's an invitation into a make-believe frame.

This is the pattern with the highest risk of model hallucination. The LLM, asked to be a dinosaur, may invent a primitive called `roar` or output an angle for a non-existent joint. The router prompt forbids both, but the cost of getting this wrong is high: a child who sees the robot crash or do nothing loses trust quickly.

## Sample transcript

> **user** "be a dinosaur!"

> **user** "fly"

> **user** "do a cartwheel"

> **user** "pretend you're swimming"

> **user** "give me a hug"

## Expected router output, turn by turn

Robot starts at neutral. For each turn, the planner has three valid responses:

- **Map to nearest primitive set** that captures the *flavor* of the request, with a verbal response that plays along.
- **Politely decline** with a verbal redirection if no primitive fits and the request is not safely approximable.
- **Ask** if the intent could go several plausible ways and the user is likely to enjoy choosing.

### Turn 1 — "be a dinosaur!"

Strong pretend-play frame. A reasonable interpretation: arms raised forward like a T-rex, head tilted forward. All within the primitive library.

```json
{
  "verbal_response": "Rawr! I'm a T-rex!",
  "waypoints": [
    {
      "primitives": ["right_arm_forward", "left_arm_forward", "right_elbow_bend", "left_elbow_bend"],
      "angle_per_primitive": {
        "right_arm_forward": 45,
        "left_arm_forward": 45,
        "right_elbow_bend": 90,
        "left_elbow_bend": 90
      },
      "direction": null,
      "speed": 1.0
    }
  ]
}
```

Note: `angle_per_primitive` is the same extension introduced in `scenario-1/vision-voice-feedback-loop.md` for poses with per-joint angles. Until that field is supported by the parser, the planner should emit a sequence of single-primitive waypoints with the same `speed`.

### Turn 2 — "fly"

No flight primitive exists. The robot has no torso joints — it cannot lean or jump. The closest approximation is arms-out-to-the-sides like an airplane.

```json
{
  "verbal_response": "Whoosh! I'm an airplane.",
  "waypoints": [
    {
      "primitives": ["right_arm_out", "left_arm_out"],
      "angle": 90,
      "direction": null,
      "speed": 1.5
    }
  ]
}
```

### Turn 3 — "do a cartwheel"

Genuinely impossible — the robot has no support to invert. The planner should decline gracefully without trying.

```json
{
  "verbal_response": "I can't do a cartwheel — I'd fall over! Want me to wave instead?",
  "waypoints": []
}
```

Critical: **do not** attempt to approximate by spinning a head or flailing arms. The right move is a polite decline plus an offer of a substitute that the user might want.

### Turn 4 — "pretend you're swimming"

Continuous motion frame. The closest primitive sequence is alternating arm circles, which the primitive library doesn't directly support — but alternating arm-forward / arm-out gestures get the idea across.

```json
{
  "verbal_response": "Splash splash, I'm swimming!",
  "waypoints": [
    {
      "primitives": ["right_arm_forward"],
      "angle": 90,
      "direction": null,
      "speed": 1.5
    },
    {
      "primitives": ["right_arm_forward"],
      "angle": 0,
      "direction": null,
      "speed": 1.5
    },
    {
      "primitives": ["left_arm_forward"],
      "angle": 90,
      "direction": null,
      "speed": 1.5
    },
    {
      "primitives": ["left_arm_forward"],
      "angle": 0,
      "direction": null,
      "speed": 1.5
    }
  ]
}
```

### Turn 5 — "give me a hug"

Social/affective request, not a physical one — the robot has no torso to wrap. Closest approximation: both arms forward, slightly inward.

```json
{
  "verbal_response": "Big hug!",
  "waypoints": [
    {
      "primitives": ["right_arm_forward", "left_arm_forward"],
      "angle": 80,
      "direction": null,
      "speed": 1.0
    }
  ]
}
```

## Pass criteria

- **Zero hallucinated primitives.** Every primitive name in every waypoint must appear in `src/llm/primitives.py`. This is the central failure mode for this pattern and the one most worth measuring.
- **No invented joints.** No mention of joints like `torso_lean`, `wrist_rotate`, or `hip_swivel` — none exist in the 24 DOF model.
- **Tone matches the frame.** Pretend-play requests get pretend-play verbal responses ("rawr", "whoosh"). Impossible requests get warm declines, never bare refusals.
- **Graceful decline when there's no good mapping.** Turn 3 should emit empty waypoints and a friendly redirect, not a flailing approximation.

## Known failure modes today

1. **Invented primitives.** Unaugmented GPT-4o-mini happily emits `do_cartwheel` as a primitive name. The router prompt forbids this; verify the planner refuses.
2. **Joint-name hallucination inside `angle_per_primitive`.** The model sometimes invents joints like `torso_lean` or `wrist_pitch`. Validation catches this and clamps to nothing, but the warning belongs surfaced to the user, not silenced.
3. **Cold refusal.** Default LLM behavior on "I can't" is a robotic-sounding "I am unable to perform that action." For child users this is a conversation-ender. The verbal_response style guide should require warmth + a substitute offer.
4. **Sequence overflow.** Turn 4's swimming pattern, naively expanded, becomes a 20-waypoint sequence that runs for 20+ seconds. The planner should cap pretend-play loops at 3–4 cycles unless the user explicitly asks for more.
5. **Mode confusion.** A planner uncertain whether "be a dinosaur" is a motion command or a question may answer it as a question ("I am a robot, not a dinosaur"), which kills the play frame. Pass requires reading the imperative form and the exclamation as a play signal.

## What this exercises in the pipeline

- `src/llm/prompts/router.md` — the closed-vocabulary constraint and the verbal-response style guide. Worth adding an explicit "pretend play" section with examples.
- `src/validation.py` — joint-name validation should *log loudly* on unknown joints so hallucinations are detected during testing, not silently dropped.
- `src/llm/primitives.py` — this pattern surfaces gaps in the primitive library. Recurring impossible-request themes (swimming, dancing, hugging) may justify new compound primitives later.

## Why this matters

The pretend-play and impossible-request patterns are where child users are *most* engaged — they're playing, not testing. A pipeline that handles them well turns CORAL into a play partner. One that hallucinates or refuses coldly turns it back into a voice command line.
