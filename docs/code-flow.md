# Code Flow: Voice to Robot Movement

How spoken text gets translated into physical robot motion, file by file.

---

## 1. Audio Capture → Transcription
**`src/coral_agent/server.py`** (WebSocket `/ws`)

Mic audio arrives as a base64-encoded WebM blob over the WebSocket. The server decodes it and calls `transcribe_audio()`, which runs faster-whisper locally to produce a text string.

---

## 2. Text → Motion Plan (LLM)
**`src/coral_agent/server.py`** → **`src/coral_agent/prompts/router.md`**

The transcribed text is bundled with the current joint state (in degrees) and sent to the LLM (GPT-4o). The system prompt in `router.md` instructs the LLM to respond with structured JSON:

```json
{
  "verbal_response": "Sure, waving now!",
  "waypoints": [
    { "primitives": ["right_arm_forward"], "angle": 90, "speed": 2.0 }
  ]
}
```

---

## 3. Waypoints → Joint Positions (radians)
**`src/coral_agent/server.py`** `resolve_wp_entry()` → **`src/coral_agent/primitives.py`** `resolve_primitive()`

Each waypoint entry is resolved into a `dict[str, float]` of joint names → radian values. For example `right_arm_forward` at 90° becomes `{"r_sho_pitch": 1.571}`. Multiple primitives in one waypoint get merged into a single joint dict.

**`src/coral_agent/validation.py`** then clamps everything to safe joint limits and checks for sign errors (e.g. LLM said "turn left" but gave a positive pan value).

---

## 4. Joint Radians → ServoCommands (0–1000 integers)
**`src/coral_agent/server.py`** `execute_waypoints()` → **`src/coral_agent/robot/angle_utils.py`**

Each joint's radian value is converted to a Hiwonder servo unit (0–1000 scale, where 500 = center/neutral, full range = 240°):

```
units = 500 + round(degrees(rad) × 1000/240)
```

The waypoint's speed multiplier is converted to a duration in milliseconds:

```
duration_ms = round(1000 / speed)   # speed=1.0 → 1000ms, speed=5.0 → 200ms
```

These become `ServoCommand(servo_id, position, duration_ms)` objects, with servo IDs looked up from **`src/coral_agent/robot/servo_config.py`** (e.g. `r_sho_pitch` → ID 14).

---

## 5. ServoCommands → Physical Motion
**`src/coral_agent/robot/sim_controller.py`** `SimController.send_commands()`

For each command, a thread is spawned that linearly interpolates `set_joint_position()` on the MuJoCo simulator over the specified `duration_ms` in 20ms steps. All joints move concurrently (threads run in parallel), then the function blocks until all finish.

In Phase 2, this layer gets replaced by `AiNexHardwareController` which sends the same `ServoCommand` structs over UART to the physical servos at 115200 baud — the rest of the pipeline above stays identical.

---

## Summary

```
Mic audio (WebM)
  └─ server.py: transcribe_audio() [faster-whisper]
       └─ Text string
            └─ server.py: LLM call with router.md prompt [GPT-4o]
                 └─ JSON: verbal_response + waypoints[]
                      └─ server.py: resolve_wp_entry()
                           └─ primitives.py: resolve_primitive()  →  {joint: rad}
                                └─ validation.py: clamp + sign-check
                                     └─ server.py: execute_waypoints()
                                          └─ angle_utils.py: rad → 0-1000 units + speed → ms
                                               └─ servo_config.py: joint name → servo ID
                                                    └─ sim_controller.py: threaded interpolation
                                                         └─ mujoco_sim.py: set_joint_position()
                                                              [Phase 2: UART to physical servos]
```
