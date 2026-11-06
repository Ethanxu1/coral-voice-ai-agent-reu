# System Architecture

A high-level map of what CORAL is made of and how the parts talk to each other.

For installation and how to start everything, see the [README](../README.md). For the voice-to-motion path in file-by-file detail, see [code-flow.md](code-flow.md).

---

## 1. What the system does

A child speaks to the AiNex humanoid robot. The robot listens, decides what was meant, and either responds conversationally or moves — imitating a pose the child strikes, or following a spoken instruction like "raise your right arm." The child can then correct the pose in words and save it.

Everything perceptual and cognitive runs on a laptop. The Pi does nothing but drive servos.

---

## 2. The two machines

```
┌───────────────────────── Mac (laptop) ─────────────────────────┐
│                                                                │
│  Frontend   :5173 Docker  React + Three.js, child-facing UI    │
│  Backend    :8000 Docker  Whisper, LLM, TTS, motion, MuJoCo    │
│  Postgres   :5432 Docker  saved poses                          │
│  Vision     :8001 host    Webcam → MediaPipe → joint targets   │
│                                                                │
└────────────────────────────┬───────────────────────────────────┘
                             │  HTTP  (ROBOT_IP:9000)
                             ▼
┌───────────────────── Raspberry Pi ─────────────────────────────┐
│  ainex Docker container — ROS Noetic                           │
│  nodes/server.py → servo bus → physical AiNex                  │
└────────────────────────────────────────────────────────────────┘
```

The split exists because the Pi cannot run the perception and language stack, and because the demo must work with no robot attached at all. **Simulation mode is the default**: `./run.sh` drives a MuJoCo model instead of hardware, over the same interface; `./run.sh -live` also drives the robot.

`./run.sh` starts the Docker services with `docker compose` and the vision server on the host, because Docker on macOS cannot reach a webcam. On Linux the backend container uses the host network (`docker-compose.linux.yml`) so it reaches the vision server on localhost.

See [hardware.md](hardware.md) for how to reach the Pi and get code onto it.

---

## 3. Subsystems

### Frontend — `frontend/`

React + TypeScript + Vite. Three.js (`@react-three/fiber`) renders the robot; the pages under `frontend/src/pages/` are separate experiences sharing `frontend/src/components/`; backend calls go through `frontend/src/api/` and endpoints are set in `frontend/src/config.ts`.

| Page | Purpose |
|---|---|
| `Welcome` | Landing screen — offers the tutorial or a skip straight to the demo |
| `RefinedDemo` | The main child-facing demo — the one used for experiments |
| `tutorial/` | Guided walkthrough, one file per screen |
| `RockPaperScissors` | Learn gestures and play against CORAL — see [rock-paper-scissors.md](rock-paper-scissors.md) |
| `TestFunctionality`, `PoseTester`, `SubjectSelect` | Developer tools: joint jogging, raw servo poses, re-ID tuning |

Demo flow lives in `frontend/src/demo/useRefinedDemoMachine.ts` — an explicit state machine (`IDLE → SUBJECT_SELECT → LISTENING → COUNTDOWN → CAPTURED → FINETUNE → NAMING → …`, with `FOLLOWING`, `LIBRARY`, `EXIT_CONFIRM`, and `ERROR` as additional stages). When reasoning about *why the demo did something*, this file is usually the answer; the backend is stateless with respect to demo progression.

### Backend — `backend/app/`, port 8000

The hub. A FastAPI app that owns:

- **Speech-to-text** — faster-whisper, running locally on CPU. Audio never leaves the laptop.
- **Intent classification** — [`backend/app/llm/intent_classifier.py`](../backend/app/llm/intent_classifier.py), regex-first with an LLM fallback. See [intent-classifier.md](intent-classifier.md).
- **Motion planning** — the LLM turns a motion description into waypoints of named primitives, guided by [`backend/app/llm/prompts/router.md`](../backend/app/llm/prompts/router.md).
- **Safety** — self-collision clamping and a fall check on every dispatch path.
- **The simulator** — MuJoCo, in-process.
- **Text-to-speech** — OpenAI TTS ([`services/tts.py`](../backend/app/services/tts.py)); every spoken reply goes out as an `audio_response` frame over `/ws`, and `POST /speak` serves pages outside the chat pipeline.
- **Pose library** — saving, listing, and replaying named poses, stored in Postgres ([`data/pose_db.py`](../backend/app/data/pose_db.py)).

Code layout: `main.py` (app factory, lifespan, entry points), `api/routes/` (HTTP and WebSocket endpoints), `services/` (chat, intent, motion dispatch, follow mode, TTS, transcription), `llm/` (classifier, primitives, prompts), `schemas/` (Pydantic models), `config.py` (all settings).

Prompts are Markdown files in `backend/app/llm/prompts/` rather than string literals, so they can be edited without touching Python. The model is set in one place, `LLM_MODEL` in [`backend/app/config.py`](../backend/app/config.py).

### Vision server — `backend/app/vision/`, port 8001

Separate process, separate port, because it owns the webcam and runs a continuous loop that shouldn't compete with request handling.

- `pose_estimator.py` — MediaPipe landmarks plus the capture state machine (`idle → countdown → collecting → frozen`), including the 3-second countdown and 3-second collection window.
- `pose_to_robot.py` — the retargeting core. Converts MediaPipe world landmarks into robot joint targets in a **torso-local frame**, so shoulder pitch and roll are decoupled from each other and from global torso rotation. Legs use a separate pelvis frame so bending at the waist doesn't swing the robot's legs.
- `leg_modes.py` — selectable leg strategies for `/map-features` (legs stand still unless `CORAL_ENABLE_LEG_TRACKING=true`).
- `subject_selector.py` — multi-person re-identification: the child who raises a hand is the one followed.
- `frame_broadcaster.py` — streams frames to the frontend.

**Shadow convention:** the child's true right side drives the robot's right side, so the robot copies the child directly rather than mirroring them like a partner facing them. This falls out of two flips that cancel each other: `pose_estimator.py` flips the camera frame before MediaPipe runs (so the on-screen preview reads like a reflection), which swaps MediaPipe's own left/right landmark labels relative to the child's true sides, and `pose_to_robot.py` swaps those labels back when mapping to robot joints. Tracing either file in isolation looks like a mirror mapping — this is the single most common source of confusion when reading the code.

### Pose capture — `/map-features`

The bridge from "what the camera sees" to "what the robot does," and the path all three experiments exercise.

Worth knowing at this level: **`/map-features` lives on the vision server (8001), not the main server**, and the frontend orchestrates two separate calls — vision retargets and returns servo commands without dispatching anything, then the frontend posts those to the main server's `/move` for safety checks and execution. A `leg_mode` parameter selects how the legs are driven; the arms always use live torso-frame retargeting.

Mechanics — the response shape, the visibility gates that abort a capture, the `leg_mode` options, and the encoding invariant between the two endpoints — are in [code-flow.md](code-flow.md).

### Robot control — `backend/app/robot/`

An abstract `RobotController` ([`interface.py`](../backend/app/robot/interface.py)) with two implementations — `sim_controller.py` (MuJoCo) and `hardware_controller.py` (HTTP to the Pi) — so nothing upstream knows or cares which is live. Swapping them is how the same demo runs with or without a physical robot.

They differ in unit conversion, not structure; see [code-flow.md](code-flow.md) for the sim-versus-hardware details.

`backend/app/robot/pi/` holds the ROS package deployed to the Pi — `nodes/server.py` (HTTP → servos), plus `body.py`, `head.py`, and `vision.py`.

### Safety — `backend/app/collision/`

A self-collision clamp and a fall check, both applied before dispatch on every path that moves the robot.

This layer exists because neither source of poses is body-aware: retargeting maps a human's geometry without knowing what the robot can do to itself, and the LLM generates joint targets from language. Everything upstream is therefore free to propose poses that would be unsafe, and this is what makes executing them acceptable. Details in [code-flow.md](code-flow.md).

---

## 4. How a request flows

**Voice command** ("raise your right arm"):

```
mic → /ws → whisper → intent classifier → motion planner (LLM)
    → primitives → validation → collision + fall check → servo commands
    → sim or Pi
```

**Pose imitation** ("capture my pose"):

```
mic → /ws → whisper → intent classifier → capture intent
    → frontend: 3s countdown
    → POST :8001/map-features → MediaPipe landmarks → torso-frame retargeting
                              → servo commands + frame returned to frontend
    → POST :8000/move         → collision + fall check
    → sim or Pi
```

Note that the frontend, not the backend, sequences this — the countdown, the call to `/map-features`, and the call to `/move` are three separate steps in `useRefinedDemoMachine.ts`, with a fixed UI delay between the last two.

Both converge at the safety layer. That convergence is deliberate — it means the experiments measure the same dispatch path a child experiences.

---

## 5. Cross-cutting conventions

**Left and right are the robot's**, everywhere in the code. Combined with the shadow convention above: a person's right arm drives the robot's right arm.

**Angles are radians internally**, degrees at the LLM boundary, and 0–1000 Hiwonder units at the servo boundary.

**Prompts are files**, not literals — `backend/app/llm/prompts/*.md`.

**The frontend holds demo state**; the backend is stateless per request except for the simulator and pose library.

**Tracing is optional.** LLM calls route through Langfuse when keys are present and silently don't when they aren't.

---

## 6. Where to look

| I want to… | Start at |
|---|---|
| Install and run it | [README](../README.md) |
| Trace voice → motion in detail | [code-flow.md](code-flow.md) |
| Understand intent routing | [intent-classifier.md](intent-classifier.md) |
| Work with the physical robot | [hardware.md](hardware.md) |
| Reproduce an experiment | [scenarios/](scenarios/) |
| Change what the robot says | `backend/app/llm/prompts/`, `backend/app/services/intent.py` (system replies) |
| Change how poses map to joints | `backend/app/vision/pose_to_robot.py` |
| Change the demo's flow | `frontend/src/demo/useRefinedDemoMachine.ts` |
