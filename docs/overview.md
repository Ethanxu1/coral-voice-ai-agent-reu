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
│  Frontend        :5173   React + Three.js, the child-facing UI │
│  Main server     :8000   Whisper, LLM, motion planning, MuJoCo │
│  Vision server   :8001   Webcam → MediaPipe → joint targets    │
│  Speaker server  :5002   pyttsx3 text-to-speech                │
│                                                                │
└────────────────────────────┬───────────────────────────────────┘
                             │  HTTP  (ROBOT_IP:9000)
                             ▼
┌───────────────────── Raspberry Pi ─────────────────────────────┐
│  ainex Docker container — ROS Noetic                           │
│  robot_server.py → servo bus → physical AiNex                  │
└────────────────────────────────────────────────────────────────┘
```

The split exists because the Pi cannot run the perception and language stack, and because the demo must work with no robot attached at all. **Simulation mode is the default**: `uv run server` drives a MuJoCo model instead of hardware, over the same interface.

See [hardware.md](hardware.md) for how to reach the Pi and get code onto it.

---

## 3. Subsystems

### Frontend — `frontend/`

React + TypeScript + Vite. Three.js (`@react-three/fiber`) renders the robot; the pages under `frontend/src/pages/` are separate experiences sharing one component library:

| Page | Purpose |
|---|---|
| `Welcome` | Landing screen — offers the tutorial or a skip straight to the demo |
| `RefinedDemo` | The main child-facing demo — the one used for experiments |
| `Tutorial` | Guided walkthrough |
| `ProDemo`, `MoveMate` | Developer-facing / alternate demo surfaces |
| `PoseTester`, `JointGizmo`, `RobotViewer`, `PoseVisualization` | Debug and inspection tools |
| `SubjectSelect` | Experiment session setup |

Demo flow lives in `frontend/src/demo/useRefinedDemoMachine.ts` — an explicit state machine (`IDLE → SUBJECT_SELECT → LISTENING → COUNTDOWN → CAPTURED → FINETUNE → NAMING → …`, with `FOLLOWING`, `LIBRARY`, `EXIT_CONFIRM`, and `ERROR` as additional stages). When reasoning about *why the demo did something*, this file is usually the answer; the backend is stateless with respect to demo progression.

### Main server — `src/server.py`, port 8000

The hub. A FastAPI app that owns:

- **Speech-to-text** — faster-whisper, running locally on CPU. Audio never leaves the laptop.
- **Intent classification** — [`src/llm/intent_classifier.py`](../src/llm/intent_classifier.py), regex-first with an LLM fallback. See [intent-classifier.md](intent-classifier.md).
- **Motion planning** — the LLM turns a motion description into waypoints of named primitives, guided by [`src/llm/prompts/router.md`](../src/llm/prompts/router.md).
- **Safety** — self-collision clamping and a fall check on every dispatch path.
- **The simulator** — MuJoCo, in-process.
- **Pose library** — saving, listing, and replaying named poses.

Prompts are Markdown files in `src/llm/prompts/` rather than string literals, so they can be edited without touching Python. The model is set in one place, [`src/llm/config.py`](../src/llm/config.py).

### Vision server — `src/vision/`, port 8001

Separate process, separate port, because it owns the webcam and runs a continuous loop that shouldn't compete with request handling.

- `pose_estimator.py` — MediaPipe landmarks plus the capture state machine (`idle → countdown → collecting → fitting → frozen`), including the 3-second countdown and 3-second collection window.
- `pose_to_robot.py` — the retargeting core. Converts MediaPipe world landmarks into robot joint targets in a **torso-local frame**, so shoulder pitch and roll are decoupled from each other and from global torso rotation. Legs use a separate pelvis frame so bending at the waist doesn't swing the robot's legs.
- `pose_classifier.py` — MobileNetV3 checkpoint classifying the observed pose.
- `smpl_fit.py` / `smpl_loader.py` — optional per-user body-shape calibration, so the same pose maps to the same joint angles across adults and children. Degrades silently if the SMPL weights aren't installed.
- `frame_broadcaster.py` — streams frames to the frontend.

**Mirror convention:** the person's right side drives the robot's left arm, so the robot behaves like a partner facing the child rather than a shadow behind them. This mirroring is the single most common source of confusion when reading the code.

### Pose capture — `/map-features`

The bridge from "what the camera sees" to "what the robot does," and the path all three experiments exercise.

Worth knowing at this level: **`/map-features` lives on the vision server (8001), not the main server**, and the frontend orchestrates two separate calls — vision retargets and returns servo commands without dispatching anything, then the frontend posts those to the main server's `/move` for safety checks and execution. A `leg_mode` parameter selects how the legs are driven; the arms always use live torso-frame retargeting.

Mechanics — the response shape, the visibility gates that abort a capture, the `leg_mode` options, and the encoding invariant between the two endpoints — are in [code-flow.md](code-flow.md).

### Robot control — `src/robot/`

An abstract `RobotController` ([`interface.py`](../src/robot/interface.py)) with two implementations — `sim_controller.py` (MuJoCo) and `hardware_controller.py` (HTTP to the Pi) — so nothing upstream knows or cares which is live. Swapping them is how the same demo runs with or without a physical robot.

They differ in unit conversion, not structure; see [code-flow.md](code-flow.md) for the sim-versus-hardware details.

`src/robot/pi/` holds the ROS package deployed to the Pi — `nodes/server.py` (HTTP → servos), plus `body.py`, `head.py`, and `vision.py`.

### Safety — `src/collision/`

A self-collision clamp and a fall check, both applied before dispatch on every path that moves the robot.

This layer exists because neither source of poses is body-aware: retargeting maps a human's geometry without knowing what the robot can do to itself, and the LLM generates joint targets from language. Everything upstream is therefore free to propose poses that would be unsafe, and this is what makes executing them acceptable. Details in [code-flow.md](code-flow.md).

### Speaker — `src/speaker/`, port 5002

pyttsx3 text-to-speech, played back through `sounddevice`/`soundfile` rather than pyttsx3's own playback (which segfaults on some platforms). Scripted lines live in `scripts.py`, requested by identifier so spoken copy stays in one place rather than scattered through the UI. A `qwen-tts` dependency and a standalone harness under `tests/qwen3-tts-test/` exist for an in-progress evaluation of a neural TTS replacement, but `speaker_server.py` does not use it yet.

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

**Left and right are the robot's**, everywhere in the code. Combined with the mirroring above: a person's right arm drives the robot's left arm.

**Angles are radians internally**, degrees at the LLM boundary, and 0–1000 Hiwonder units at the servo boundary.

**Prompts are files**, not literals — `src/llm/prompts/*.md`.

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
| Change what the robot says | `src/speaker/scripts.py`, `src/llm/prompts/` |
| Change how poses map to joints | `src/vision/pose_to_robot.py` |
| Change the demo's flow | `frontend/src/demo/useRefinedDemoMachine.ts` |
