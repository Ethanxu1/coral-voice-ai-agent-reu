# LLM Robot Control Implementation

## Overview

This system provides voice/text control of an Apptronik Apollo humanoid robot through a multi-stage LLM architecture. The implementation addresses the core challenge identified in research: **LLMs lack geometric grounding and struggle with raw angle regression**.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         User Message                                │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    STAGE 1: Intent Classification                   │
│                      (src/coral_agent/intent.py)                    │
│                                                                     │
│  Fast-path keyword detection OR LLM classification:                 │
│  • motion_command      → Pass to Stage 2                            │
│  • rollback_and_retry  → Rollback state, then retry with context    │
│  • correction          → Adjust current state                       │
│  • undo                → Rollback only                              │
│  • reset               → Return to neutral                          │
│  • conversation        → Respond directly                           │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    STAGE 2: Two-Agent Motion Planning               │
│                      (src/coral_agent/server.py)                    │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  ROUTER AGENT (prompts/router.md)                             │  │
│  │  • Determines if request can use a primitive                  │  │
│  │  • Outputs: PRIMITIVE (with name) or RAW_REQUIRED             │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                        │                      │                     │
│                        ▼                      ▼                     │
│         ┌──────────────────────┐  ┌──────────────────────────────┐  │
│         │  PRIMITIVE PATH      │  │  KINEMATICS AGENT            │  │
│         │  Uses pre-tested     │  │  (prompts/kinematics.md)     │  │
│         │  motion primitive    │  │  Computes raw joint angles   │  │
│         └──────────────────────┘  │  with sign rule validation   │  │
│                                   └──────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      Validation Layer                               │
│                   (src/coral_agent/validation.py)                   │
│                                                                     │
│  • Validates joint values against MuJoCo model limits               │
│  • Auto-clamps out-of-range values with warnings                    │
│  • Motion sign validation (catches L/R reversal mistakes)           │
│  • Logs violations for debugging                                    │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      MuJoCo Simulator                               │
│               (src/coral_agent/simulator/mujoco_sim.py)             │
│                                                                     │
│  • Smooth waypoint interpolation                                    │
│  • Real-time visualization                                          │
└─────────────────────────────────────────────────────────────────────┘
```

## Module Descriptions

### 1. Intent Classifier (`src/coral_agent/intent.py`)

The first stage of the architecture. Uses fast-path keyword detection with LLM fallback for ambiguous cases.

**Key Components:**
- `IntentType` enum: Defines all possible intent categories (MOTION_COMMAND, ROLLBACK_AND_RETRY, CORRECTION, UNDO, RESET, CONVERSATION)
- `IntentResult`: Result dataclass with intent_type, confidence, correction_context, retry_instruction
- `quick_intent_check()`: Fast keyword-based detection for high-confidence patterns (avoids LLM call)
- `classify_intent()`: LLM-based classification using `prompts/intent.md` system prompt
- `parse_intent_response()`: Parses LLM JSON output
- `infer_intent_from_keywords()`: Fallback keyword-based classification when JSON parsing fails
- `build_retry_context()`: Constructs context for retry scenarios
- `build_correction_context()`: Constructs context for correction requests

**Why Two Stages?**
- Separates "what does the user want?" from "how do we achieve it?"
- Fast-path detection avoids unnecessary LLM calls for obvious intents
- Enables semantic understanding of corrections without hardcoded patterns
- Allows retry scenarios to include "what went wrong" context

### 2. Motion Planner (`src/coral_agent/server.py`)

The second stage implements a **two-agent architecture** for robust motion planning.

**Two-Agent Flow:**

1. **Router Agent** (`prompts/router.md`):
   - Receives user request with current robot state
   - Decides if a pre-programmed primitive can satisfy the request
   - Outputs `PRIMITIVE` (with exact primitive name) or `RAW_REQUIRED`
   - Has strict rejection rules for specific angles or directions

2. **Kinematics Agent** (`prompts/kinematics.md`):
   - Only called when Router outputs `RAW_REQUIRED`
   - Computes exact joint angles with chain-of-thought reasoning
   - Enforces critical sign rules for L/R arm symmetry
   - Handles plural requests ("both arms", "elbows")

**Key Features:**
- **Structured JSON Output**: Forces chain-of-thought reasoning via `thought_process` field
- **Primitive Preference**: Router routes to primitives when possible
- **Degree-to-Radian Hints**: `detect_degrees_in_request()` provides conversion hints
- **Plural Detection**: `detect_plural_arms()` reminds LLM to include both sides
- **Hierarchical Memory**: Manages short-term (6 exchanges), mid-term summaries, and last action context
- **Conversation Recording**: All interactions saved to `recordings/` for debugging

**Server Components:**
- `HierarchicalMemory`: Manages conversation context across exchanges
- `ConversationRecorder`: Records interactions to timestamped JSON files
- `Waypoint`: Internal representation with joints, speed, reasoning, primitive_name
- `normalize_waypoint_joints()`: Handles LLM JSON format variations
- `execute_waypoints()`: Smooth interpolation execution

### 3. Validation Layer (`src/coral_agent/validation.py`)

Catches and corrects invalid joint values before execution.

**Key Components:**
- `JointLimit`: Class with min/max bounds, `clamp()` and `is_valid()` methods
- `ValidationResult`: Stores original joints, validated joints, violations, unknown joints
- `JOINT_LIMITS`: Dictionary of 24 joint limits from MuJoCo model (torso, neck, arms, legs)
- `validate_waypoint()`: Validates and optionally clamps joint values
- `validate_motion_sign()`: Checks L/R sign conventions (catches common LLM mistakes)
- `describe_joint_state()`: Generates human-readable state descriptions

**Motion Sign Validation:**
The `validate_motion_sign()` function catches cases where the LLM uses wrong signs for left/right arms:
```python
# User says "right arm out" but LLM outputs positive value
issues = validate_motion_sign("right arm out", {"r_shoulder_aa": 1.57})
# Returns: ["Right arm out requires NEGATIVE r_shoulder_aa, got 1.57"]
```

**Example:**
```python
# LLM outputs r_shoulder_aa: 1.5 (wrong - exceeds limit of 0.12)
validation = validate_waypoint({"r_shoulder_aa": 1.5})
# Result: r_shoulder_aa clamped to 0.122173 with warning logged
```

### 4. Motion Primitives (`src/coral_agent/primitives.py`)

Library of 40+ tested, validated poses that eliminate guessing.

**Available Primitives:**
| Category | Primitives |
|----------|------------|
| **Neutral/Rest** | `neutral`, `arms_down` |
| **T-Pose/Arms** | `t_pose`, `left_arm_out`, `right_arm_out`, `arms_up`, `arms_up_and_out` |
| **Pointing** | `point_forward`, `point_forward_left` |
| **Waving** | `wave_right`, `wave_left` |
| **Head** | `look_left`, `look_right`, `look_up`, `look_down`, `look_far_left`, `look_far_right`, `nod_yes`, `shake_no` |
| **Angle Positions** | `both_arms_45_out`, `left_arm_90_out`, `right_arm_90_out`, `left_arm_45_out`, `right_arm_45_out` |
| **Expressive** | `thinking`, `shrug` |

**Key Data:**
- `PRIMITIVES`: Dict of `MotionPrimitive` objects (name, description, joints, tags)
- `PRIMITIVE_ALIASES`: LLM alternative phrasings (e.g., "wave" → "wave_right")
- `DEGREE_TO_RADIAN`: Common conversions (15° through 180°)

**Key Functions:**
- `get_primitive(name)`: Get primitive by name with fuzzy matching
- `find_primitive_by_tags()`: Tag-based search
- `get_primitives_list()`: Format primitives for LLM prompt injection
- `detect_degrees_in_request()`: Extract degree values and provide radian hints
- `detect_plural_arms()`: Detect dual-arm requests and provide hints

**Fuzzy Matching:**
The system includes alias mapping for common LLM mistakes:
```python
"left arm down" → "arms_down"
"both arms out" → "t_pose"
"wave" → "wave_right"
```

### 5. State Management (`src/coral_agent/state.py`)

Enables rollback for "undo" and "try again" commands.

**Key Components:**
- `StateManager`: Stack-based checkpoint system (10 max)
- `execute_rollback()`: Smooth interpolation back to previous state
- Checkpoint saved before each waypoint execution

### 6. Hierarchical Memory (`src/coral_agent/server.py`)

Manages conversation context efficiently via the `HierarchicalMemory` class.

**Memory Tiers:**
- **Short-term**: Last 6 exchanges (full detail)
- **Mid-term**: Summarized older exchanges (auto-condensed when short-term overflows)
- **Last action**: Most recent waypoints for modification requests
- **Last user request**: Stored for retry/correction context
- **Last action summary**: e.g., "Moved joints: r_shoulder_aa, l_shoulder_aa"

**Key Methods:**
- `add_exchange()`: Adds user/assistant pair, manages rollover to mid-term
- `get_context_for_llm()`: Formats history for LLM messages
- `get_last_waypoints_summary()`: Human-readable summary of last executed waypoints

### 7. Pydantic Schemas (`src/coral_agent/schemas.py`)

Enforces structured LLM output.

```python
class LLMResponse(BaseModel):
    thought_process: str  # Required reasoning
    waypoints: list[WaypointOutput]
    verbal_response: str

class WaypointOutput(BaseModel):
    reasoning: str
    primitive: str | None  # Use primitive OR joints
    joints: dict[str, float] | None
    speed: float = 1.0

class RollbackCommand(BaseModel):
    command_type: str  # "undo" or "reset"
    steps: int
```

Includes `EXAMPLE_RESPONSE` and `EXAMPLE_RAW_JOINTS` for prompt construction.

### 8. Prompt Files (`src/coral_agent/prompts/`)

System prompts are externalized to markdown files for easy iteration.

| File | Purpose |
|------|---------|
| `main.md` | Main motion planning prompt (legacy single-agent mode) |
| `router.md` | Router agent - decides PRIMITIVE vs RAW_REQUIRED |
| `kinematics.md` | Kinematics agent - computes raw joint angles |
| `intent.md` | Intent classifier - categorizes user intent |

**Prompt Injection:**
Prompts contain `{primitives_list}` placeholder that gets replaced with the current primitives list at runtime:
```python
router_prompt = get_router_prompt().replace("{primitives_list}", get_primitives_list())
```

## Data Flow Example

### Normal Motion Command (Primitive Path)

```
User: "Wave at me"

1. Intent Classifier:
   - quick_intent_check() finds no special patterns
   - Falls through to motion_command

2. Router Agent receives:
   - CURRENT_STATE: {joints...}
   - STATE_DESCRIPTION: "neutral standing position"
   - USER_REQUEST: "Wave at me"

3. Router outputs:
   {
     "status": "PRIMITIVE",
     "primitive_name": "wave_right",
     "reasoning": "User wants a wave gesture, wave_right matches",
     "verbal_response": "Waving at you!"
   }

4. System looks up "wave_right" primitive joints
5. Validation: Clamps any out-of-range values
6. Execution: Smooth interpolation to target
```

### Normal Motion Command (Raw Joints Path)

```
User: "Raise your right arm to the side at 45 degrees"

1. Intent Classifier → motion_command

2. Hint Detection:
   - detect_degrees_in_request() → "45° = 0.79 radians"
   - Hint injected into context

3. Router Agent outputs:
   {
     "status": "RAW_REQUIRED",
     "reasoning": "User specifies exact angle (45°) not matching any primitive"
   }

4. Kinematics Agent receives context + hint
   Outputs:
   {
     "thought_process": "Right arm sideways 45°. 45° = 0.79 rad. Right arm out requires NEGATIVE r_shoulder_aa.",
     "waypoints": [{"joints": {"r_shoulder_aa": -0.79}, "speed": 1.0}],
     "verbal_response": "Raising right arm 45 degrees."
   }

5. Validation: validate_motion_sign() checks sign convention ✓
6. Execution: Smooth interpolation to target
```

### Retry Scenario

```
User: "No, that was wrong, try again"

1. Intent Classifier → rollback_and_retry
   - correction_context: "Previous movement was wrong"
   - retry_instruction: "Raise your right arm to the side"

2. System rolls back to previous state via execute_rollback()

3. Router/Kinematics receives:
   ## RETRY CONTEXT - Previous attempt failed
   Original request: Raise your right arm to the side
   What robot did: Moved joints: r_shoulder_aa
   What was wrong: Previous movement was wrong
   IMPORTANT: Double-check your joint signs!

   CURRENT_STATE: {joints after rollback}
   USER_REQUEST: Raise your right arm to the side

4. LLM tries again with warning context
```

## Key Design Decisions

### 1. Primitives Over Raw Angles

**Problem**: LLMs consistently guess wrong values for angles.

**Solution**: Pre-defined, tested poses (40+) that the LLM can reference by name. Router agent preferentially selects primitives before falling back to raw joint computation.

### 2. Two-Agent Motion Planning

**Problem**: Single LLM prompt tries to do too much - routing, kinematics, and response generation.

**Solution**: Split into Router (decides primitive vs raw) and Kinematics (computes angles) agents. Router handles easy cases instantly; Kinematics handles complex math with focused prompting.

### 3. Fast-Path Intent Detection

**Problem**: Calling LLM for every message is slow and expensive.

**Solution**: `quick_intent_check()` uses pattern matching for obvious intents (undo, reset, greetings) before falling back to LLM classification.

### 4. Validation with Clamping

**Problem**: Invalid joint values could damage robot or crash simulator.

**Solution**: Auto-clamp to limits with warnings, never reject completely. Motion sign validation catches L/R reversal errors.

### 5. Chain-of-Thought Prompting

**Problem**: LLMs make sign errors without reasoning.

**Solution**: Force `thought_process` field that must explain the choice. Kinematics agent prompt includes step-by-step reasoning template.

### 6. Explicit Sign Documentation

**Problem**: Left/right arm signs are opposite and confusing.

**Solution**: Multiple redundant reminders with examples:
- In kinematics.md prompt
- In router.md primitive descriptions
- In main.md fallback prompt
- Motion sign validation as final safety net

### 7. Externalized Prompts

**Problem**: Prompts embedded in Python code are hard to iterate on.

**Solution**: System prompts stored as markdown files in `prompts/` directory. Easy to edit, version control, and A/B test.

### 8. Hierarchical Memory

**Problem**: Context grows unbounded, exceeding LLM token limits.

**Solution**: Three-tier memory (short-term detail, mid-term summaries, last action) keeps context bounded while preserving relevant history.

## File Structure

```
src/coral_agent/
├── __init__.py
├── server.py          # FastAPI server, WebSocket, two-agent motion planner (924 lines)
├── intent.py          # Stage 1: Intent classifier with fast-path detection (331 lines)
├── validation.py      # Joint limit and sign validation (314 lines)
├── primitives.py      # Motion primitives library (533 lines)
├── state.py           # State checkpointing and rollback (232 lines)
├── schemas.py         # Pydantic models (122 lines)
├── bot.py             # Pipecat voice AI integration (124 lines)
├── test_local.py      # Local dialogue testing (72 lines)
├── prompts/           # Externalized system prompts
│   ├── main.md        # Main motion planning prompt
│   ├── router.md      # Router agent prompt
│   ├── kinematics.md  # Kinematics agent prompt
│   └── intent.md      # Intent classifier prompt
└── simulator/
    ├── __init__.py    # Exports ApolloSimulator, G1Simulator
    └── mujoco_sim.py  # MuJoCo simulator wrapper (373 lines)
```

**Total Python code:** ~2,650 lines

## Configuration

### Ollama Model

The system uses `llama3.2` by default for all agents (intent, router, kinematics). Model is hardcoded in:
```python
# In server.py - Router and Kinematics agents
ollama.chat(model="llama3.2", messages=[...], format="json")

# In intent.py - Intent classifier
ollama.chat(model="llama3.2", messages=[...], format="json")
```

### Prompts

Edit the markdown files in `src/coral_agent/prompts/` to modify agent behavior:
- `router.md` - Controls when primitives are used vs raw joints
- `kinematics.md` - Controls joint angle computation logic
- `intent.md` - Controls intent classification categories

### Joint Limits

Limits are defined in `validation.py` and extracted from the MuJoCo model XML. If the robot model changes, update `JOINT_LIMITS` dictionary. Current limits cover 24 joints:
- Torso: yaw, roll, pitch
- Neck/Head: yaw, roll, pitch
- Arms (L/R): shoulder_aa, shoulder_ie, shoulder_fe, elbow, wrist (3 DOF each)
- Legs (L/R): hip (3 DOF), knee, ankle (2 DOF)

## Debugging

### Conversation Recordings

All interactions are saved to `recordings/conversation_YYYYMMDD_HHMMSS.json`:
```json
{
  "interactions": [
    {
      "user": "raise arm",
      "assistant": "...",
      "waypoints_extracted": [...],
      "waypoints_executed": [...]
    }
  ]
}
```

### Logging

The system uses `loguru` for logging:
- Intent classification results
- Primitive resolution
- Validation violations
- Waypoint execution

## Gesture Library (`src/coral_agent/gesture_library.py`)

Animated social gestures mapped from robotics research (Pepper robot animations, social robotics papers).

**Available Gestures:**
| Category | Gestures |
|----------|----------|
| **Greetings** | `wave_hello`, `wave_hello_left` |
| **Head** | `nod_yes`, `shake_no`, `head_tilt_curious` |
| **Emotional** | `happy_reaction`, `sad_reaction`, `shrug`, `thinking` |
| **Attention** | `look_around`, `attention_here`, `beckon` |
| **Conversational** | `listening`, `acknowledge`, `bow` |

**Key Components:**
- `AnimatedGesture`: Dataclass with keyframes (joint positions) and durations
- `GESTURE_LIBRARY`: Registry of all gestures by name
- `GESTURE_ALIASES`: Alternative names (e.g., "yes" → "nod_yes")
- `get_gesture()`: Get gesture by name, alias, or tag search

## Motor Tuning

The MuJoCo model (`assets/apptronik_apollo/apptronik_apollo.xml`) has position controller gains (kp) tuned for each joint:

**Head/Neck Motors (increased for faster response):**
- `neck_yaw`: kp=150 (controls left/right head turn)
- `neck_roll`: kp=80 (controls head tilt)
- `neck_pitch`: kp=80 (controls nodding up/down)

**Arm Motors (original values):**
- `l_shoulder_aa`/`r_shoulder_aa`: kp=395 (sideways)
- `l_shoulder_fe`/`r_shoulder_fe`: kp=214 (forward/back)
- `l_elbow_fe`/`r_elbow_fe`: kp=200 (elbow bend)

The head motors were originally 10-50x weaker than arm motors (kp=8-28), causing sluggish head movements. Increasing kp values makes gestures like nodding and head shaking more responsive and visible.

## Degrees to Radians

The prompts include a clear conversion formula for arbitrary angles:

**Formula:** `radians = degrees × 0.01745` (or degrees × π/180)

**Common values:**
| Degrees | Radians |
|---------|---------|
| 30° | 0.52 |
| 45° | 0.79 |
| 60° | 1.05 |
| 90° | 1.57 |
| 100° | 1.75 |
| 120° | 2.09 |

This enables the LLM to handle arbitrary angle requests (not just 45° or 90°).

## Future Improvements

1. **Fine-tuned Intent Classifier**: Train a small model specifically for intent classification
2. **Visual Feedback**: Use camera to verify pose correctness
3. **Learning from Corrections**: Store successful retry patterns for few-shot prompting
4. **Multi-turn Planning**: Handle complex sequences with intermediate checkpoints
5. **Voice Integration**: Full Pipecat integration via `bot.py` (currently partial)
6. **Model Selection**: Allow different models for different agents (fast model for router, capable model for kinematics)
7. **Primitive Auto-Discovery**: Generate primitives from demonstration recordings

## Additional Files

### Voice Bot (`src/coral_agent/bot.py`)

Pipecat integration for voice-based dialogue (alternative interface to WebSocket).

**Components:**
- Daily transport for real-time audio
- Ollama LLM service
- Silero VAD (Voice Activity Detection)
- OpenAILLMContext for conversation history

### Local Testing (`src/coral_agent/test_local.py`)

Simple CLI interface for testing dialogue without WebSocket frontend.
