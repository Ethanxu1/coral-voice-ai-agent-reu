# Motion Block Studio Design

**Date:** 2026-10-09
**Status:** Approved design, pending implementation plan
**Base:** Pull request #10 (`origin/pr/10`)
**Product language:** English only

## 1. Purpose

Motion Block Studio lets a user teach CORAL recognizable full-body human poses, author deterministic robot poses, combine robot poses into reusable sequences, and connect recognition to response through visual behavior rules.

The primary behavior is:

```text
IF a person holds a learned pose for 0.7 seconds
THEN preview the configured robot motion sequence in the simulator
```

Any visible person may trigger a rule. When several people qualify, the system selects the highest-confidence completed hold. Physical-robot execution is never enabled implicitly; the default and persisted output mode is `simulator`.

## 2. Goals

- Restore complete leg rendering and use hips, knees, and ankles in pose recognition.
- Map captured human leg poses to robot leg joints.
- Train each human pose class from 3–5 or more examples using a lightweight few-shot classifier.
- Save a robot pose once, either from human retargeting or manual simulator editing.
- Compose robot poses into ordered sequences with hold and transition durations.
- Connect a learned human pose to a robot sequence with an `IF → THEN` rule.
- Preview every sequence in MuJoCo before optional hardware execution.
- Persist projects, samples, blocks, sequences, and rules in SQLite across restarts.
- Export and import a complete, versioned JSON project package.
- Render scalable skeletal thumbnails and optionally export them as PNG.
- Keep all production UI copy in English.

## 3. Non-goals for the First Version

- Recognizing temporal human actions such as walking or waving as time-series classes.
- Training neural networks or requiring a GPU.
- Cloud synchronization or user accounts.
- Concurrent execution of multiple robot response sequences.
- Automatic physical-robot execution merely because hardware is connected.

Dynamic robot motion is supported by composing static `RobotPose` blocks. Dynamic human-action recognition can be added later behind the same recognizer interface.

## 4. User Experience

### 4.1 Three-column workspace

The selected layout is a three-column studio:

1. **Block Library** — Human Poses, Robot Poses, and Sequences.
2. **Rule Canvas** — visual `IF HumanPose → THEN Sequence` composition.
3. **Live Preview** — recognition state, selected person, hold progress, confidence, simulator output, and safety results.

The application header displays Camera, Backend, and Vision connectivity. It also displays the output mode. `Simulator` is the default. `Live Robot` requires an explicit user action and automatically returns to off when hardware becomes unavailable.

### 4.2 Human-pose training

1. The user selects **Train a human pose** and supplies a unique English name.
2. The UI confirms that the complete body is visible.
3. A countdown captures 3–5 stable examples.
4. Each sample is quality-checked for visibility, stability, and outlier distance.
5. Rejected samples are explained and immediately retaken.
6. A representative full-body SVG thumbnail is generated.
7. The pose class becomes available as an `IF` block.

Additional examples can be appended later without rebuilding unrelated classes.

### 4.3 Robot-pose authoring

A `RobotPose` may originate from:

- a captured human pose retargeted to the complete robot body, including legs; or
- manual adjustment of the simulator robot.

The pose is saved once as deterministic robot joint targets. Before save, the pose must pass both collision and fall checks. Unsafe poses remain editable but cannot become executable blocks until they pass.

### 4.4 Sequence composition

Users drag `RobotPose` blocks into a sequence. Every step stores:

- hold duration;
- transition duration from the preceding step; and
- order.

The simulator previews the complete sequence, not merely individual endpoints. Safety validation covers every interpolated transition. A failure identifies the step and reason and prevents execution of the sequence.

### 4.5 Rule execution

Each enabled rule connects one `HumanPose` to one robot sequence. Recognition follows these constraints:

- the pose must remain recognized for 0.7 seconds;
- a rule fires once per completed hold;
- execution is exclusive;
- new triggers are ignored while a sequence is running;
- a global cooldown begins after completion;
- a user must leave the recognized pose before the same rule may re-arm.

For multiple people, recognition scores are computed independently. The highest-confidence person who completes the hold wins. The Live Preview identifies the triggering person and displays confidence.

## 5. Architecture

The end-to-end path is:

```text
Vision Server
  → Full-body Feature Extractor
  → PoseRecognizer
  → Trigger Engine
  → Sequence Player
  → MuJoCo Safety Gate
  → Simulator or explicitly enabled Live Robot
```

### 5.1 Vision Server

The existing MediaPipe pipeline continues to publish 33 body landmarks for every tracked person. The full-body skeleton renderer adds torso, hip, knee, ankle, heel, and foot connections. Leg landmarks remain visible even if hardware output is disabled.

### 5.2 Feature Extractor

The extractor converts visible landmarks into a person-independent feature vector containing:

- normalized joint positions relative to body anchors;
- major joint angles;
- normalized limb direction vectors;
- body-side proportions; and
- per-feature visibility weights.

Normalization removes image position, person scale, and camera aspect ratio. Camera reflection is handled explicitly. Features with insufficient visibility are masked rather than silently treated as valid zeros.

### 5.3 PoseRecognizer

`PoseRecognizer` is an interface so the classification implementation can change without altering storage, rules, or UI.

The first implementation is a weighted k-nearest-neighbor classifier:

- training consists of validating and storing labeled feature vectors;
- distance is visibility-weighted;
- the nearest neighbors vote with inverse-distance weights;
- recognition requires a minimum confidence;
- the winning class must beat the runner-up by a configurable margin; and
- otherwise the result is `Unknown pose`.

This design runs on CPU, works with 3–5 initial examples, updates immediately when a sample is added, and serializes cleanly into JSON.

### 5.4 Trigger Engine

The trigger engine owns hold timers, per-person recognition state, arbitration, exclusive execution, re-arming, and cooldown. The frontend only displays engine state; it does not implement trigger timing.

### 5.5 Sequence Player and Safety Gate

The sequence player resolves immutable snapshots of referenced robot poses before playback. It interpolates each transition using the configured duration and submits the same path to collision and fall validation. Simulator playback is always available. Hardware dispatch requires both a successful safety result and an explicitly enabled live-output session.

## 6. Persistent Data Model

SQLite schema migrations replace the current startup-time deletion of saved poses.

### 6.1 Core entities

- `projects`: project metadata, schema version, timestamps, and settings.
- `human_poses`: name, thumbnail SVG, recognition thresholds, hold duration, and enabled state.
- `pose_samples`: human-pose reference, normalized features, visibility weights, mirror metadata, quality metrics, and timestamp.
- `robot_poses`: name, joint targets, thumbnail SVG, authoring source, last safety result, and timestamps.
- `sequences`: name and timestamps.
- `sequence_steps`: sequence reference, robot-pose reference, order, hold duration, and transition duration.
- `behavior_rules`: human-pose reference, sequence reference, cooldown, priority, and enabled state.

Foreign keys are enabled. Deletion is protected: the API reports all referencing sequences and rules before a block can be removed. Referential changes are transactional.

### 6.2 JSON project package

Exports contain:

```json
{
  "schema_version": 1,
  "project": {},
  "human_poses": [],
  "training_samples": [],
  "robot_poses": [],
  "sequences": [],
  "rules": [],
  "settings": {
    "output_mode": "simulator"
  }
}
```

Import validates the schema version, IDs, references, numeric ranges, feature dimensions, and joint names before writing. The complete import occurs in one transaction. Invalid packages leave the current project unchanged.

## 7. API and Streaming Boundaries

The backend exposes these resource-oriented API families under `/studio`:

- `/projects` for project CRUD and active-project selection;
- `/projects/{id}/export` and `/projects/import` for versioned JSON packages;
- `/human-poses` and `/human-poses/{id}/samples` for pose classes and training data;
- `/robot-poses` with explicit capture-from-human and capture-from-simulator operations;
- `/sequences` and `/sequences/{id}/steps` for ordered motion composition;
- `/sequences/{id}/preview` for simulator-only validation and playback;
- `/rules` for behavior-rule CRUD and enablement;
- `/output-mode` for session-scoped simulator/live selection; and
- `/ws/studio` for recognition, hold, cooldown, preview, and execution events.

The boundary follows these rules:

- CRUD operations use HTTP JSON.
- Sample capture and recognition state use the existing vision WebSocket family.
- Sequence preview and execution progress use a backend WebSocket event stream.
- SVG thumbnails are generated from stored landmark or joint data, not accepted as authoritative motion data.
- The backend validates every duration, threshold, joint value, and foreign-key reference.

## 8. Error Handling

- Missing full-body landmarks: `Full body not visible` and no sample save.
- Low-quality or unstable sample: reject with a specific retake reason.
- Ambiguous classification: `Unknown pose` and no trigger.
- Interrupted hold: reset progress immediately.
- Busy player or active cooldown: ignore new triggers while publishing the current state.
- Unsafe pose or transition: stop before execution and identify the failing block.
- Hardware unavailable: keep simulator active, force `Live Robot` off, and show `Robot unavailable`.
- Import validation failure: return structured errors and roll back completely.
- Auto-save failure: preserve unsaved editor state and expose `Retry`.

Errors are actionable, visible, and never silently converted into robot commands.

## 9. Safety and Security

- Simulator-only output is the persistent default.
- Live hardware permission is session-scoped and explicit.
- Every robot pose and every interpolated sequence transition passes collision and fall checks.
- Imported JSON is treated as untrusted input and is size-limited and schema-validated.
- SQL statements are parameterized.
- SVG thumbnails are generated internally and rendered without executable content.
- Recognition confidence alone never bypasses the hold, exclusivity, cooldown, or safety gates.

## 10. Testing Strategy

### 10.1 Unit tests

- full-body normalization and aspect handling;
- mirror handling;
- joint-angle and limb-vector features;
- visibility weighting and masking;
- weighted k-NN votes, thresholds, margins, and unknown rejection;
- per-person 0.7-second holds, arbitration, re-arming, exclusivity, and cooldown;
- sequence interpolation; and
- database CRUD and migrations.

### 10.2 Integration tests

- training workflow and sample-quality rejection;
- persistence across backend restarts;
- JSON export/import round trip and rollback;
- behavior-rule editing and reference protection;
- simulator sequence preview and safety failures; and
- forced shutdown of live mode when hardware disconnects.

### 10.3 Frontend tests

- three-column workspace states;
- English-only production copy;
- full-body SVG rendering;
- drag/drop ordering and duration editing;
- hold-progress, confidence, person, cooldown, and error displays; and
- simulator/live-mode controls.

### 10.4 End-to-end tests

Recorded multi-person landmark streams verify that the correct person and rule win, one sequence executes, new triggers are ignored while busy, and output remains simulator-only by default.

## 11. Acceptance Criteria

- The Live Preview renders a full-body skeleton including hips, knees, and ankles.
- A human pose can be trained from 3–5 samples and recognized with an unknown class available.
- Any visible person may trigger; the highest-confidence completed hold wins.
- Recognition fires only after a continuous 0.7-second hold.
- Human leg pose retargeting produces robot leg targets.
- Unsafe poses or sequence transitions never execute.
- Users can author RobotPoses from camera retargeting or manual simulator editing.
- Users can compose, reorder, time, preview, save, and reuse sequences.
- Rules connect learned human poses to robot sequences.
- All data survives restart and round-trips through a versioned JSON package.
- Simulator mode is the default; physical output requires explicit enablement.
- All production UI text is English.

## 12. Delivery Boundaries

Implementation should be staged so each layer is independently testable:

1. persistence and data contracts;
2. full-body features and few-shot recognition;
3. trigger engine;
4. robot pose and sequence services with safety validation;
5. three-column English UI;
6. import/export and end-to-end verification.

This order keeps existing PR #10 behavior operational while the new studio is introduced behind a separate route until acceptance criteria pass.
