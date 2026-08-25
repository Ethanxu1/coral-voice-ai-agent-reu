# Code Flow: Voice to Robot Movement

How spoken text gets translated into physical robot motion, file by file.

Two paths reach the robot and converge at the safety layer: a **voice command** ("raise your right arm"), traced in §1–7, and a **pose capture** ("capture my pose"), traced in §8. For the system as a whole rather than these two paths, see [overview.md](overview.md).

---

## 1. Audio Capture → Transcription
**[`src/server.py`](../src/server.py)** (WebSocket `/ws`)

Mic audio arrives as a base64-encoded WebM blob over the WebSocket. The server decodes it and calls `transcribe_audio()`, which runs **faster-whisper locally on CPU** (int8) to produce a text string. No audio leaves the laptop.

The model size comes from `WHISPER_MODEL_SIZE` (default `base`) and is loaded lazily on first use, then cached. Transcription is seeded with a domain prompt from [`src/llm/prompts/whisper.md`](../src/llm/prompts/whisper.md), which biases decoding toward the vocabulary this demo expects ("capture my pose", body-part words) instead of generic English.

---

## 2. Text → Intent
**[`src/llm/intent_classifier.py`](../src/llm/intent_classifier.py)**

Before anything is planned, the text is classified: is this a motion command, a system command, chit-chat, or too ambiguous to act on? Regex matchers handle the common cases instantly and the LLM handles the rest. Only finalized motion descriptions continue down this path.

Full detail in [intent-classifier.md](intent-classifier.md).

---

## 3. Text → Motion Plan (LLM)
**[`src/server.py`](../src/server.py)** `process_chat_message()` → **[`src/llm/prompts/router.md`](../src/llm/prompts/router.md)**

The motion description is bundled with the current joint state (in degrees) and sent to the LLM. The model is set centrally in [`src/llm/config.py`](../src/llm/config.py) as `LLM_MODEL` — currently `gpt-5.4-mini`, with a commented DeepSeek-via-Fireworks alternative in the same file. Calls go through the Langfuse-wrapped OpenAI client, so tracing is automatic when keys are present.

The system prompt in `router.md` instructs the LLM to respond with structured JSON:

```json
{
  "action": "motion",
  "waypoints": [
    { "primitives": ["right_arm_forward"], "angle": 90, "direction": null, "speed": 2.0 }
  ],
  "verbal_response": "Sure, waving now!",
  "satisfied": null
}
```

---

## 4. Waypoints → Joint Positions (radians)
**[`src/server.py`](../src/server.py)** `resolve_wp_entry()` → **[`src/llm/primitives.py`](../src/llm/primitives.py)** `resolve_primitive()`

Each waypoint entry is resolved into a `dict[str, float]` of joint names → radian values. For example `right_arm_forward` at 90° becomes `{"r_sho_pitch": 1.571}`. Multiple primitives in one waypoint merge into a single joint dict.

Primitives are **absolute** joint setters computed from the stand pose, not deltas from the robot's current configuration — `left_arm_out(90)` means "put the arm at 90° from stand," regardless of where it started. Each is individually clamped to its `JOINT_LIMITS` bound on the way out.

**[`src/validation.py`](../src/validation.py)** then clamps everything to safe joint limits and checks for sign errors (e.g. the LLM said "turn left" but gave a positive pan value).

---

## 5. Safety: collision and fall checks
**[`src/server.py`](../src/server.py)** `collision_checked_targets()` → **[`src/collision/`](../src/collision/)**

Retargeting and primitives have no notion of the robot's own body, so before any dispatch the target pose is shadow-rolled through two checks:

- **Self-collision** — [`collision_checker.py`](../src/collision/collision_checker.py) finds the largest fraction of the commanded motion that stays collision-free and clamps to it. The reported `safe_fraction` is `1.0` when the full move is clean.
- **Fall / stability** — [`stability_checker.py`](../src/collision/stability_checker.py) evaluates whether the pose would tip the robot. A failed check blocks the move entirely — nothing is dispatched — so the caller can report it rather than executing a partial motion.

This runs on the shared path used by `/move`, `/set-pose`, and `/poses/play`, so every entry point gets the same guarantees. The fall check can be toggled at runtime via `/settings/fall-check`.

---

## 6. Joint Radians → ServoCommands (0–1000 integers)
**[`src/server.py`](../src/server.py)** `execute_waypoints()` → **[`src/robot/angle_utils.py`](../src/robot/angle_utils.py)**

Each joint's radian value becomes a Hiwonder servo unit (0–1000 scale, 1000 units = 240°):

```
units = clamp(500 + round(degrees(rad) × 1000/240), 0, 1000)
```

The `500` neutral offset is **sim-only**. Physical servos have per-joint neutrals and some run in the opposite direction from the MuJoCo model, so hardware mode converts through [`src/robot/hardware_angle_utils.py`](../src/robot/hardware_angle_utils.py) instead:

```
delta_rad = rad − HW_STAND_RAD[joint]
hw_units  = STAND_PULSE[joint] + round(delta_rad × TICKS_PER_RAD × HW_DIRECTION[joint])
```

The result is then clamped to that joint's measured-safe `HW_SERVO_LIMITS` range (not the generic 0–1000) — a tighter, per-servo bound than the sim-side clamp.

`HW_STAND_RAD` must stay equal, joint for joint, to the `stand` keyframe in `assets/ainex/ainex.xml` — that equality is what makes the calibrated bent-knee stand render identically in sim and on hardware.

The waypoint's speed multiplier becomes a duration, clamped to 200–5000 ms:

```
duration_ms = clamp(round(1000 / speed), 200, 5000)   # speed=1.0 → 1000ms, 5.0 → 200ms
```

These become `ServoCommand(servo_id, position, duration_ms)` objects, with servo IDs looked up from [`src/robot/servo_config.py`](../src/robot/servo_config.py) (e.g. `r_sho_pitch` → ID 14).

---

## 7. ServoCommands → Motion
**[`src/robot/interface.py`](../src/robot/interface.py)** → `SimController` or `AiNexHardwareController`

`RobotController` is an abstract base with two implementations behind one interface, so everything above this line is identical in both modes:

- **[`sim_controller.py`](../src/robot/sim_controller.py)** — spawns a thread per command that linearly interpolates `set_joint_position()` on the MuJoCo simulator over `duration_ms` in 20 ms steps. All joints move concurrently, then the call blocks until every thread finishes.
- **[`hardware_controller.py`](../src/robot/hardware_controller.py)** — converts to hardware units and POSTs the same `ServoCommand` structs over HTTP to `robot_server.py` running on the Pi at `ROBOT_IP:ROBOT_AGENT_PORT`, which drives the physical servos.

Which one is live depends on how the server was started — `uv run server` for sim, `ROBOT_IP=… uv run robot` for hardware.

---

## 8. The other path: pose capture
**[`src/vision/vision_server.py`](../src/vision/vision_server.py)** `/map-features` → **[`src/server.py`](../src/server.py)** `/move`

"Capture my pose" skips the LLM motion planner entirely. Instead of generating joint targets from language, the system reads them off the person's body — then rejoins the path above at step 5.

**`/map-features` is on the vision server (8001), not the main server.** The frontend orchestrates two calls:

```
frontend  ──POST :8001/map-features?leg_mode=…──▶  vision server
          ◀── { pose_detected, commands[], targets, leg_mode, body_landmarks, image_b64 }

frontend  ──POST :8000/move────────────────────▶  main server
          ◀── { status, count, safety }
```

### Step one — retarget (vision server)

Takes the most recent MediaPipe landmarks and camera frame, maps the person's body geometry to joint angles via `compute_joint_targets()` in [`pose_to_robot.py`](../src/vision/pose_to_robot.py), and returns servo commands for the caller to execute. The landmarks and source frame come back too, so the UI can show the child what Coral saw. **Nothing is dispatched here.**

Two gates can stop a capture before it produces anything:

- **Hips must be visible** (`hips_detected`). Arm retargeting is anchored on the hips, so without them only the head could move. Returns `pose_detected: false` with a reframing message rather than a partial pose.
- **Knees must clear a visibility threshold** before the legs are driven. Knee visibilities are logged on every call, since "why didn't the legs move?" is otherwise hard to answer after the fact.

The `leg_mode` query parameter selects how the *legs* are driven; the arms always use live torso-frame retargeting. Modes are defined in [`leg_modes.py`](../src/vision/leg_modes.py):

| `leg_mode` | Behavior |
|---|---|
| `retarget` (default) | Live pelvis-frame hip pitch/roll and knee bend |
| `legacy` | The old, anatomically wrong atan2 mapping (`hip_yaw ← swing`) |
| `classify` | MobileNetV3 classifies the pose, legs snap to that canned stance |
| `buckets` | Knee/ankle bend and hip yaw quantized into discrete stances, snapped to fixed targets |

The selected mode is logged on every call, so it's answerable from one log line rather than inferred from the resulting joint values.

### Step two — dispatch (main server)

The frontend posts the returned commands to `/move`, which decodes them back to radians, runs the same collision and fall checks as §5, and sends the result to the simulator, the hardware, or both.

### The encoding invariant

`/map-features` **always** encodes with the uniform 500-centre sim map (`rad_to_servo_units`), regardless of sim or hardware mode, so `/move` must decode with the matching `servo_units_to_rad`. Conversion to hardware units happens later, inside `hardware_controller.py` (§6).

Decoding with the per-joint hardware-calibrated inverse instead silently corrupts every joint whose `STAND_PULSE` isn't 500 *or* whose `HW_STAND_RAD` isn't 0 — that is, every leg and arm joint except hip roll and hip yaw. (The knees are the trap here: `STAND_PULSE["l_knee"]` and `STAND_PULSE["r_knee"]` **are** 500, same as sim neutral, but `HW_STAND_RAD` is ±0.925 rad for them, so they'd still be corrupted by the wrong inverse — `STAND_PULSE == 500` alone isn't a safe joint indicator.) A captured stand-pose knee at 0.925 rad round-tripped to roughly double that (~1.85 rad), a completely different bend, while the trivially-calibrated hip joints survived and made the bug look intermittent.

---

## Summary

**Voice command:**

```
Mic audio (WebM)
  └─ server.py: transcribe_audio()                    [faster-whisper, local CPU]
       └─ Text string
            └─ intent_classifier.py: classify_intent() [regex → LLM fallback]
                 └─ Motion description
                      └─ server.py: process_chat_message() + router.md   [LLM_MODEL]
                           └─ JSON: verbal_response + waypoints[]
                                └─ server.py: resolve_wp_entry()
                                     └─ primitives.py: resolve_primitive()  →  {joint: rad}
                                          └─ validation.py: clamp + sign-check
                                               └─ collision/: self-collision clamp + fall check
                                                    └─ server.py: execute_waypoints()
                                                         └─ angle_utils.py    (sim)
                                                            hardware_angle_utils.py (hardware)
                                                              └─ servo_config.py: joint → servo ID
                                                                   ├─ sim_controller.py  → mujoco_sim.py
                                                                   └─ hardware_controller.py → HTTP → Pi
```

**Pose capture:**

```
Webcam frame + MediaPipe landmarks
  └─ vision_server.py: /map-features?leg_mode=…      [:8001]
       └─ hips_detected() gate
            └─ pose_to_robot.py: compute_joint_targets()  →  {joint: rad}
                 └─ rad_to_servo_units()  →  servo commands  →  returned to frontend
                      └─ server.py: /move                  [:8000]
                           └─ servo_units_to_rad()
                                └─ collision/: self-collision clamp + fall check
                                     ├─ sim_controller.py  → mujoco_sim.py
                                     └─ hardware_controller.py → HTTP → Pi
```
