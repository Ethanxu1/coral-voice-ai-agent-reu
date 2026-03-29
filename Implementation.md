# LLM Robot Control Implementation

## Overview

This system provides voice/text control of an Apptronik Apollo humanoid robot through a two-stage LLM architecture. The implementation addresses the core challenge identified in research: **LLMs lack geometric grounding and struggle with raw angle regression**.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         User Message                                │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    STAGE 1: Intent Classifier                       │
│                      (src/coral_agent/intent.py)                    │
│                                                                     │
│  Classifies user intent into one of:                                │
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
│                    STAGE 2: Motion Planner                          │
│                      (src/coral_agent/server.py)                    │
│                                                                     │
│  • Chain-of-Thought reasoning before action                         │
│  • Prefers motion primitives over raw angles                        │
│  • Outputs structured JSON with waypoints                           │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      Validation Layer                               │
│                   (src/coral_agent/validation.py)                   │
│                                                                     │
│  • Validates joint values against MuJoCo model limits               │
│  • Auto-clamps out-of-range values with warnings                    │
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

The first stage of the two-stage architecture. Uses a fast LLM to classify user intent before motion planning.

**Key Components:**
- `IntentType` enum: Defines all possible intent categories
- `classify_intent()`: Main function that calls LLM for classification
- `parse_intent_response()`: Parses LLM JSON output
- `infer_intent_from_keywords()`: Fallback keyword-based classification
- `build_retry_context()`: Constructs context for retry scenarios

**Why Two Stages?**
- Separates "what does the user want?" from "how do we achieve it?"
- Enables semantic understanding of corrections without hardcoded patterns
- Allows retry scenarios to include "what went wrong" context

### 2. Motion Planner (`src/coral_agent/server.py`)

The second stage that generates actual robot waypoints.

**Key Features:**
- **Structured JSON Output**: Forces chain-of-thought reasoning
- **Primitive Preference**: Encourages use of tested poses over raw angles
- **Degree-to-Radian Conversion**: Explicit conversion table in prompt
- **Sign Documentation**: Clear documentation of which signs mean what

**System Prompt Structure:**
```
1. Output format (required JSON structure)
2. Motion primitives list
3. Degree-to-radian conversion table
4. Joint reference with signs
5. Common mistakes to avoid
6. Examples with correct reasoning
```

### 3. Validation Layer (`src/coral_agent/validation.py`)

Catches and corrects invalid joint values before execution.

**Key Components:**
- `JOINT_LIMITS`: Dictionary of all joint limits from MuJoCo model
- `validate_waypoint()`: Validates and clamps joint values
- `describe_joint_state()`: Generates human-readable state descriptions

**Example:**
```python
# LLM outputs r_shoulder_aa: 1.5 (wrong - exceeds limit of 0.12)
validation = validate_waypoint({"r_shoulder_aa": 1.5})
# Result: r_shoulder_aa clamped to 0.122173 with warning logged
```

### 4. Motion Primitives (`src/coral_agent/primitives.py`)

Library of tested, validated poses that eliminate guessing.

**Available Primitives:**
| Primitive | Description |
|-----------|-------------|
| `neutral` | Standing position, arms at sides |
| `t_pose` | Both arms horizontal |
| `wave_right` / `wave_left` | Waving gesture |
| `point_forward` | Pointing forward |
| `look_left` / `look_right` | Head turns |
| `arms_up` / `arms_down` | Arm positions |
| `right_arm_90_out` / `left_arm_90_out` | Single arm 90° outward |
| `look_far_left` / `look_far_right` | Maximum head turns |

**Fuzzy Matching:**
The system includes alias mapping for common LLM mistakes:
```python
"left arm down" → "arms_down"
"both arms out" → "t_pose"
```

### 5. State Management (`src/coral_agent/state.py`)

Enables rollback for "undo" and "try again" commands.

**Key Components:**
- `StateManager`: Stack-based checkpoint system (10 max)
- `execute_rollback()`: Smooth interpolation back to previous state
- Checkpoint saved before each waypoint execution

### 6. Hierarchical Memory (`src/coral_agent/server.py`)

Manages conversation context efficiently.

**Memory Tiers:**
- **Short-term**: Last 6 exchanges (full detail)
- **Mid-term**: Summarized older exchanges
- **Last action**: Most recent waypoints for modification requests

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
```

## Data Flow Example

### Normal Motion Command

```
User: "Raise your right arm to the side"

1. Intent Classifier → motion_command
2. Motion Planner receives:
   - CURRENT_STATE: {joints...}
   - STATE_DESCRIPTION: "neutral standing position"
   - USER_REQUEST: "Raise your right arm to the side"

3. LLM outputs:
   {
     "thought_process": "Right arm out = negative r_shoulder_aa...",
     "waypoints": [{"joints": {"r_shoulder_aa": -1.57}, "speed": 1.0}],
     "verbal_response": "Raising right arm."
   }

4. Validation: Checks -1.57 is within [-1.61, 0.12] ✓
5. Execution: Smooth interpolation to target
```

### Retry Scenario

```
User: "No, that was wrong, try again"

1. Intent Classifier → rollback_and_retry
   - correction_context: "Previous movement was wrong"
   - retry_instruction: "Raise your right arm to the side"

2. System rolls back to previous state

3. Motion Planner receives:
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

**Solution**: Pre-defined, tested poses that the LLM can reference by name.

### 2. Two-Stage Architecture

**Problem**: Hardcoded regex patterns for "undo", "retry" miss nuanced cases.

**Solution**: LLM-based intent classification understands semantic meaning.

### 3. Validation with Clamping

**Problem**: Invalid joint values could damage robot or crash simulator.

**Solution**: Auto-clamp to limits with warnings, never reject completely.

### 4. Chain-of-Thought Prompting

**Problem**: LLMs make sign errors without reasoning.

**Solution**: Force `thought_process` field that must explain the choice.

### 5. Explicit Sign Documentation

**Problem**: Left/right arm signs are opposite and confusing.

**Solution**: Multiple redundant reminders with examples:
- In joint reference section
- In common mistakes section
- In examples

## File Structure

```
src/coral_agent/
├── __init__.py
├── server.py          # FastAPI server, WebSocket, motion planner
├── intent.py          # Stage 1: Intent classifier
├── validation.py      # Joint limit validation
├── primitives.py      # Motion primitives library
├── state.py           # State checkpointing
├── schemas.py         # Pydantic models
└── simulator/
    ├── __init__.py
    └── mujoco_sim.py  # MuJoCo simulator wrapper
```

## Configuration

### Ollama Model

The system uses `llama3.2` by default. To change:
```python
# In server.py
response = ollama.chat(model="your-model", ...)

# In intent.py
classify_intent(..., model="your-model")
```

### Joint Limits

Limits are defined in `validation.py` and extracted from the MuJoCo model XML. If the robot model changes, update `JOINT_LIMITS` dictionary.

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

## Future Improvements

1. **Fine-tuned Intent Classifier**: Train a small model specifically for intent classification
2. **Visual Feedback**: Use camera to verify pose correctness
3. **Learning from Corrections**: Store successful retry patterns
4. **Multi-turn Planning**: Handle complex sequences with intermediate checkpoints
