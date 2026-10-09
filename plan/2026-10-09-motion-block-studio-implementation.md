# Motion Block Studio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an English-only studio that learns full-body human poses from a few examples, maps them to safe robot motion sequences, and previews `IF pose → THEN sequence` rules in MuJoCo.

**Architecture:** Add a focused `app.studio` backend package for persistence, feature extraction, recognition, triggering, sequence playback, import/export, and runtime orchestration. Extend the vision payload so every detected subject carries full landmarks, then add a separate React `/motion-studio` route with Block Library, Rule Canvas, and Live Preview columns. Preserve all existing PR #10 routes and demos.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLite, NumPy, pytest, MediaPipe landmark data, React 18, TypeScript 5.6, Vite 5, Vitest, Testing Library, MuJoCo safety checkers.

**Spec:** `docs/superpowers/specs/2026-10-09-motion-block-studio-design.md`

## Global Constraints

- Production UI copy, buttons, statuses, validation messages, and placeholders must be English only.
- Human-pose recognition is static-pose recognition; temporal human-action classification is out of scope.
- Each pose class starts with 3–5 samples and may accept additional samples later.
- Recognition uses CPU-only visibility-weighted k-NN behind a `PoseRecognizer` interface; do not add a neural-network dependency.
- Any visible person may trigger; the highest-confidence completed 0.7-second hold wins deterministically.
- Only one sequence may execute at a time; new triggers are ignored while busy and during global cooldown.
- Human leg landmarks participate in recognition and retargeting.
- Every robot pose and interpolated sequence transition must pass collision and fall checks before execution.
- Simulator output is the default. Live hardware output is session-scoped and requires explicit enablement.
- SQLite data persists across restarts. JSON import is versioned, validated, size-limited, and transactional.
- Preserve existing `/home`, `/pose-tester`, `/rock-paper-scissors`, and legacy saved-pose behavior.
- Python follows PEP 8 with type hints; keep new responsibility-focused source files near 200–400 lines.

## Review Focus

- Malformed landmark values (`NaN`, infinity, missing hips/knees/ankles) must reject a sample or yield `Unknown pose`, never poison stored features.
- Simultaneous equal-confidence candidates must resolve deterministically by completed-hold timestamp and then subject ID.
- A JSON package with duplicate IDs, dangling references, unknown joints, or excessive size must roll back without changing the active project.
- Deleting a referenced RobotPose, HumanPose, or Sequence must return its dependents and leave all data intact.
- Hardware disconnect during playback must stop further hardware dispatch, force output mode back to simulator, and keep simulator state usable.

---

## File Structure

### Backend

- `backend/app/studio/models.py` — immutable domain dataclasses and enums shared across studio modules.
- `backend/app/studio/repository.py` — SQLite schema migrations, CRUD, protected deletes, and transactions.
- `backend/app/studio/features.py` — full-body validation, normalization, angle/vector features, and SVG-ready representative skeletons.
- `backend/app/studio/recognizer.py` — `PoseRecognizer` protocol and visibility-weighted k-NN implementation.
- `backend/app/studio/trigger_engine.py` — per-person holds, deterministic arbitration, re-arm, busy state, and cooldown.
- `backend/app/studio/sequence_player.py` — immutable sequence snapshots, safety preflight, simulator playback, and guarded hardware dispatch.
- `backend/app/studio/import_export.py` — versioned project package validation and transactional import/export.
- `backend/app/studio/runtime.py` — vision WebSocket consumer, recognition loop, event broadcast, and output-mode state.
- `backend/app/studio/schemas.py` — Pydantic API contracts.
- `backend/app/api/routes/studio.py` — `/studio` HTTP and `/ws/studio` endpoints.
- `backend/app/vision/pose_estimator.py` — include full body landmarks in each multi-person subject payload.
- `backend/app/main.py` — start/stop `StudioRuntime`; stop clearing saved poses on launch.
- `backend/app/state.py` — hold the runtime reference.

### Frontend

- `frontend/src/studio/types.ts` — API and event types.
- `frontend/src/studio/api.ts` — `/api/studio` HTTP client.
- `frontend/src/studio/useStudioSocket.ts` — `/ws/studio` connection and reducer.
- `frontend/src/studio/FullBodySkeleton.tsx` — safe full-body SVG renderer.
- `frontend/src/studio/BlockLibrary.tsx` — Human, Robot, and Sequence tabs.
- `frontend/src/studio/PoseTrainingDialog.tsx` — sample capture and quality feedback.
- `frontend/src/studio/RuleCanvas.tsx` — IF/THEN rule editing.
- `frontend/src/studio/SequenceEditor.tsx` — ordered robot-pose steps and timing.
- `frontend/src/studio/LivePreview.tsx` — recognition, hold, selected person, safety, and simulator status.
- `frontend/src/pages/MotionStudio.tsx` / `.css` — three-column page composition.
- `frontend/src/App.tsx` — launcher link and `/motion-studio` route.

### Tests

- `backend/tests/studio/` — repository, features, recognizer, trigger, player, API, and import/export tests.
- `backend/tests/vision/test_multi_person_payload.py` — every subject retains full landmarks.
- `frontend/src/studio/*.test.ts(x)` — Vitest component and state tests.
- `frontend/src/pages/MotionStudio.test.tsx` — English-only page and main workflow tests.

---

### Task 1: Persistent Studio Domain and SQLite Migrations

**Files:**
- Create: `backend/app/studio/__init__.py`
- Create: `backend/app/studio/models.py`
- Create: `backend/app/studio/repository.py`
- Create: `backend/tests/studio/__init__.py`
- Create: `backend/tests/studio/test_repository.py`
- Modify: `backend/app/main.py:102-107`
- Test: `backend/tests/studio/test_repository.py`

**Interfaces:**
- Produces: `StudioRepository(db_path: Path)`.
- Produces: `Project`, `HumanPose`, `PoseSample`, `RobotPose`, `Sequence`, `SequenceStep`, and `BehaviorRule` dataclasses.
- Produces: `StudioRepository.transaction()`, `export_rows(project_id)`, and protected-delete methods used by Tasks 5 and 6.

- [ ] **Step 1: Write failing persistence and migration tests**

```python
def test_data_survives_repository_reopen(tmp_path):
    db = tmp_path / "studio.db"
    repo = StudioRepository(db)
    project = repo.create_project("Classroom gestures")
    pose = repo.create_human_pose(project.id, "Hands up", 0.78, 0.7)
    repo.close()

    reopened = StudioRepository(db)
    assert reopened.get_human_pose(pose.id).name == "Hands up"


def test_referenced_robot_pose_delete_is_rejected(repo, populated_sequence):
    result = repo.delete_robot_pose(populated_sequence.steps[0].robot_pose_id)
    assert result.deleted is False
    assert result.dependents == [populated_sequence.id]


def test_transaction_rolls_back_all_rows(repo):
    with pytest.raises(RuntimeError), repo.transaction():
        repo.create_project("Will roll back")
        raise RuntimeError("stop")
    assert repo.list_projects() == []
```

- [ ] **Step 2: Run the repository tests and confirm they fail**

Run: `uv run pytest backend/tests/studio/test_repository.py -v`
Expected: FAIL because `app.studio.repository` does not exist.

- [ ] **Step 3: Add typed domain models and migration-driven repository**

```python
@dataclass(frozen=True, slots=True)
class HumanPose:
    id: str
    project_id: str
    name: str
    thumbnail_svg: str
    min_confidence: float
    hold_seconds: float
    enabled: bool


class StudioRepository:
    SCHEMA_VERSION = 1

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._migrate()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
```

Create `schema_migrations`, `projects`, `human_poses`, `pose_samples`, `robot_poses`, `sequences`, `sequence_steps`, and `behavior_rules`. Enable `PRAGMA foreign_keys = ON`, use UUID strings, parameterized SQL, unique `(project_id, name COLLATE NOCASE)` constraints, and indexes on all foreign keys.

Remove `clear_all_poses()` from the FastAPI lifespan so legacy saved poses also survive restart; do not remove the legacy table or endpoints.

- [ ] **Step 4: Run persistence tests and legacy route tests**

Run: `uv run pytest backend/tests/studio/test_repository.py backend/tests/test_extract_name.py backend/tests/test_chat_motion_plan.py -v`
Expected: PASS, including reopen, rollback, and protected-delete tests.

- [ ] **Step 5: Commit the data foundation**

```bash
git add backend/app/studio backend/tests/studio backend/app/main.py
git commit -m "feat(data): add persistent motion studio schema"
```

---

### Task 2: Full-body Features and Few-shot Recognizer

**Files:**
- Create: `backend/app/studio/features.py`
- Create: `backend/app/studio/recognizer.py`
- Create: `backend/tests/studio/test_features.py`
- Create: `backend/tests/studio/test_recognizer.py`
- Test: `backend/tests/studio/test_features.py`
- Test: `backend/tests/studio/test_recognizer.py`

**Interfaces:**
- Consumes: `PoseSample` rows from Task 1.
- Produces: `extract_pose_features(landmarks: Sequence[Mapping[str, float]]) -> PoseFeatures`.
- Produces: `validate_training_sample(...) -> SampleQuality` and `render_skeleton_svg(...) -> str`.
- Produces: `PoseRecognizer.classify(subject_id, features) -> RecognitionResult`.
- Produces: `WeightedKnnRecognizer(samples, k=3, min_confidence=0.78, margin=0.08)`.

- [ ] **Step 1: Write failing feature-quality tests**

```python
def test_translation_and_scale_do_not_change_features(full_body_pose):
    moved = transform(full_body_pose, scale=1.8, dx=0.2, dy=-0.1)
    assert extract_pose_features(moved).values == pytest.approx(
        extract_pose_features(full_body_pose).values, abs=1e-5
    )


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_non_finite_landmark_is_rejected(full_body_pose, bad):
    full_body_pose[25]["x"] = bad
    with pytest.raises(InvalidPose, match="finite"):
        extract_pose_features(full_body_pose)


def test_missing_ankle_rejects_training_sample(full_body_pose):
    full_body_pose[27]["visibility"] = 0.1
    quality = validate_training_sample(full_body_pose)
    assert quality.accepted is False
    assert quality.message == "Full body not visible"
```

- [ ] **Step 2: Run feature tests and confirm they fail**

Run: `uv run pytest backend/tests/studio/test_features.py -v`
Expected: FAIL because the extractor is missing.

- [ ] **Step 3: Implement normalized full-body features and SVG generation**

```python
FULL_BODY_JOINTS = (0, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28)


@dataclass(frozen=True, slots=True)
class PoseFeatures:
    names: tuple[str, ...]
    values: tuple[float, ...]
    weights: tuple[float, ...]

    def with_feature_weight(self, name: str, weight: float) -> "PoseFeatures":
        index = self.names.index(name)
        updated = list(self.weights)
        updated[index] = weight
        return replace(self, weights=tuple(updated))


def extract_pose_features(landmarks: Sequence[Mapping[str, float]]) -> PoseFeatures:
    checked = _finite_visible_landmarks(landmarks, FULL_BODY_JOINTS)
    hip_mid = midpoint(checked[23], checked[24])
    shoulder_mid = midpoint(checked[11], checked[12])
    scale = distance(shoulder_mid, hip_mid)
    if scale <= 1e-6:
        raise InvalidPose("Torso scale is too small")
    positions = normalized_positions(checked, origin=hip_mid, scale=scale)
    angles = joint_angles(positions)
    directions = limb_directions(positions)
    return PoseFeatures(values=positions + angles + directions, weights=visibility_weights(checked))
```

Generate SVG only from numeric coordinates using fixed element templates; never interpolate user strings into markup.

- [ ] **Step 4: Write and run failing k-NN tests**

```python
def test_weighted_knn_rejects_ambiguous_pose(samples):
    recognizer = WeightedKnnRecognizer(samples, k=3, min_confidence=0.78, margin=0.08)
    result = recognizer.classify("person-1", halfway_between_classes(samples))
    assert result.label is None
    assert result.reason == "ambiguous"


def test_low_visibility_joint_has_less_influence(samples):
    query = samples[0].features.with_feature_weight("left_ankle_x", 0.05)
    assert WeightedKnnRecognizer(samples).classify("p", query).label == samples[0].label
```

Implement inverse-distance voting with `weight = visibility / max(distance, 1e-6)`, class-normalized confidence, minimum threshold, runner-up margin, and deterministic label ordering. Run: `uv run pytest backend/tests/studio/test_features.py backend/tests/studio/test_recognizer.py -v`
Expected: PASS.

- [ ] **Step 5: Commit the recognizer**

```bash
git add backend/app/studio/features.py backend/app/studio/recognizer.py backend/tests/studio
git commit -m "feat(model): add full-body few-shot recognition"
```

---

### Task 3: Multi-person Landmark Payload and Full-leg Retargeting Contract

**Files:**
- Modify: `backend/app/vision/pose_estimator.py:858-963`
- Modify: `backend/app/vision/vision_server.py:230-351`
- Modify: `backend/app/config.py:78-87`
- Modify: `frontend/src/types/pose.ts:31-81`
- Create: `backend/tests/vision/test_multi_person_payload.py`
- Modify: `backend/tests/vision/test_pose_to_robot.py`
- Test: `backend/tests/vision/test_multi_person_payload.py`

**Interfaces:**
- Produces: every `subjects[]` WebSocket item with `body_landmarks`, not only a bbox.
- Produces: `POST /map-features?leg_mode=retarget` as the studio capture path.
- Preserves: existing selected-subject fields and legacy default behavior outside the studio.

- [ ] **Step 1: Write failing multi-person serialization tests**

```python
def test_every_subject_payload_contains_full_landmarks(fake_multi_frame):
    result = fake_multi_frame.process()
    assert len(result.subjects) == 2
    assert all(len(subject["body_landmarks"]) == 33 for subject in result.subjects)
    assert result.subjects[0]["body_landmarks"][27]["visibility"] > 0


def test_payloads_are_independent(fake_multi_frame):
    result = fake_multi_frame.process()
    result.subjects[0]["body_landmarks"][0]["x"] = 99
    assert result.subjects[1]["body_landmarks"][0]["x"] != 99
```

- [ ] **Step 2: Run the payload tests and confirm they fail**

Run: `uv run pytest backend/tests/vision/test_multi_person_payload.py -v`
Expected: FAIL because `subjects_json` omits landmarks.

- [ ] **Step 3: Serialize each subject's landmarks and type them on the frontend**

```python
subjects_json = [
    {
        "id": info.id,
        "bbox": info.bbox,
        "body_landmarks": [dict(lm) for lm in info.body_landmarks],
        "is_candidate": info.is_candidate,
        "hold_progress": round(info.hold_progress, 2),
        "depth": round(info.depth, 4),
        "metrics": info.metrics.to_dict() if info.metrics else None,
    }
    for info in selection.subjects
]
```

Add `body_landmarks: Landmark[]` to `DetectedSubject`. Keep `CORAL_ENABLE_LEG_TRACKING=false` for legacy follow mode, but have studio capture explicitly request `leg_mode=retarget` and reject low-visibility legs rather than silently saving stand-leg targets.

- [ ] **Step 4: Run vision and TypeScript verification**

Run: `uv run pytest backend/tests/vision/test_multi_person_payload.py backend/tests/vision/test_pose_to_robot.py backend/tests/vision/test_leg_modes.py -v`
Expected: PASS.
Run: `cd frontend && npm run build`
Expected: PASS with the extended subject type.

- [ ] **Step 5: Commit the vision contract**

```bash
git add backend/app/vision backend/app/config.py backend/tests/vision frontend/src/types/pose.ts
git commit -m "feat(model): expose full-body multi-person landmarks"
```

---

### Task 4: Hold, Arbitration, Busy, Re-arm, and Cooldown Engine

**Files:**
- Create: `backend/app/studio/trigger_engine.py`
- Create: `backend/tests/studio/test_trigger_engine.py`
- Test: `backend/tests/studio/test_trigger_engine.py`

**Interfaces:**
- Consumes: `RecognitionResult(subject_id, label, confidence, timestamp)`.
- Produces: `TriggerEngine.update(results, now) -> TriggerDecision | None`.
- Produces: `mark_execution_started()`, `mark_execution_finished(now)`, and `snapshot(now) -> TriggerSnapshot`.

- [ ] **Step 1: Write failing state-machine and Review Focus tests**

```python
def test_pose_must_hold_continuously_for_point_seven_seconds(engine):
    assert engine.update([seen("p1", "hands-up", 0.9)], now=0.0) is None
    assert engine.update([seen("p1", "hands-up", 0.9)], now=0.69) is None
    assert engine.update([seen("p1", "hands-up", 0.9)], now=0.70).subject_id == "p1"


def test_equal_confidence_is_deterministic(engine):
    engine.update([seen("b", "pose", 0.9), seen("a", "pose", 0.9)], now=0.0)
    decision = engine.update([seen("b", "pose", 0.9), seen("a", "pose", 0.9)], now=0.7)
    assert decision.subject_id == "a"


def test_same_pose_requires_exit_before_rearm(engine):
    fire(engine, "p1", "pose")
    engine.mark_execution_finished(now=1.0)
    assert engine.update([seen("p1", "pose", 0.99)], now=4.0) is None
    engine.update([], now=4.1)
    assert hold_until_fire(engine, "p1", "pose", start=4.2) is not None
```

- [ ] **Step 2: Run trigger tests and confirm they fail**

Run: `uv run pytest backend/tests/studio/test_trigger_engine.py -v`
Expected: FAIL because `TriggerEngine` does not exist.

- [ ] **Step 3: Implement a clock-injected deterministic engine**

```python
class TriggerEngine:
    def update(self, results: Sequence[RecognitionResult], now: float) -> TriggerDecision | None:
        if self._busy or now < self._cooldown_until:
            return None
        self._update_holds(results, now)
        eligible = [hold for hold in self._holds.values() if hold.elapsed(now) >= self.hold_seconds]
        if not eligible:
            return None
        winner = min(eligible, key=lambda h: (-h.confidence, h.completed_at(now), h.subject_id))
        self._armed.discard((winner.subject_id, winner.label))
        return TriggerDecision(winner.subject_id, winner.label, winner.confidence)
```

Reset a subject's hold immediately on missing/unknown/changed pose. Make cooldown global and keep re-arm state separate from cooldown.

- [ ] **Step 4: Run the complete trigger suite**

Run: `uv run pytest backend/tests/studio/test_trigger_engine.py -v`
Expected: PASS for hold, interruption, arbitration, busy, cooldown, and re-arm.

- [ ] **Step 5: Commit the trigger engine**

```bash
git add backend/app/studio/trigger_engine.py backend/tests/studio/test_trigger_engine.py
git commit -m "feat(model): add multi-person pose trigger engine"
```

---

### Task 5: Robot Pose Capture and Safe Sequence Player

**Files:**
- Create: `backend/app/studio/sequence_player.py`
- Create: `backend/tests/studio/test_sequence_player.py`
- Modify: `backend/app/services/motion.py`
- Test: `backend/tests/studio/test_sequence_player.py`

**Interfaces:**
- Consumes: repository `RobotPose` and `SequenceStep` snapshots from Task 1.
- Consumes: existing `collision_checked_targets`, simulator, and dispatchers.
- Produces: `SequencePlayer.preflight(sequence_id) -> SequenceSafetyReport`.
- Produces: `await SequencePlayer.play(sequence_id, output_mode) -> PlaybackResult`.
- Produces: `OutputMode.SIMULATOR` and session-only `OutputMode.LIVE_ROBOT`.

- [ ] **Step 1: Write failing sequence preflight and disconnect tests**

```python
@pytest.mark.anyio
async def test_unsafe_middle_transition_blocks_entire_sequence(player, checker):
    checker.fail_on_step = 1
    result = await player.play("sequence-1", OutputMode.SIMULATOR)
    assert result.status == "blocked"
    assert result.failed_step == 1
    assert player.dispatch_count == 0


@pytest.mark.anyio
async def test_hardware_disconnect_forces_simulator(player, hardware):
    hardware.disconnect_after_first_command = True
    result = await player.play("sequence-1", OutputMode.LIVE_ROBOT)
    assert result.status == "hardware_unavailable"
    assert player.output_mode is OutputMode.SIMULATOR
    assert hardware.command_batches == 1
```

- [ ] **Step 2: Run sequence tests and confirm they fail**

Run: `uv run pytest backend/tests/studio/test_sequence_player.py -v`
Expected: FAIL because no sequence player exists.

- [ ] **Step 3: Implement immutable snapshots, preflight, and guarded playback**

```python
async def play(self, sequence_id: str, output_mode: OutputMode) -> PlaybackResult:
    snapshot = self._repository.get_sequence_snapshot(sequence_id)
    safety = await asyncio.to_thread(self._preflight_snapshot, snapshot)
    if not safety.safe:
        return PlaybackResult.blocked(safety.failed_step, safety.reason)
    for step in snapshot.steps:
        commands = self._commands_for(step.robot_pose, step.transition_ms)
        try:
            await self._dispatch(commands, sim_only=output_mode is OutputMode.SIMULATOR)
        except RobotServerUnavailable:
            self.output_mode = OutputMode.SIMULATOR
            return PlaybackResult.hardware_unavailable()
        await asyncio.sleep(step.hold_ms / 1000)
    return PlaybackResult.completed(len(snapshot.steps))
```

Preflight every interpolated transition before the first dispatch. Extract a reusable path-validation helper from `services/motion.py` without changing existing endpoint behavior.

- [ ] **Step 4: Run player and existing safety suites**

Run: `uv run pytest backend/tests/studio/test_sequence_player.py backend/tests/test_motion_safety.py backend/tests/test_collision_check.py backend/tests/test_stability_checker.py -v`
Expected: PASS and zero dispatches for a blocked sequence.

- [ ] **Step 5: Commit safe playback**

```bash
git add backend/app/studio/sequence_player.py backend/app/services/motion.py backend/tests/studio/test_sequence_player.py
git commit -m "feat(trainer): add safe robot sequence playback"
```

---

### Task 6: Studio API, Import/Export, Runtime, and WebSocket Events

**Files:**
- Create: `backend/app/studio/schemas.py`
- Create: `backend/app/studio/import_export.py`
- Create: `backend/app/studio/runtime.py`
- Create: `backend/app/api/routes/studio.py`
- Create: `backend/tests/studio/test_import_export.py`
- Create: `backend/tests/studio/test_studio_api.py`
- Create: `backend/tests/studio/test_runtime.py`
- Modify: `backend/app/api/router.py:5-13`
- Modify: `backend/app/main.py:93-173`
- Modify: `backend/app/state.py:11-22`
- Test: `backend/tests/studio/test_studio_api.py`

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces: the `/studio` HTTP API families and `/ws/studio` event stream from the spec.
- Produces: `StudioRuntime.start()`, `stop()`, `set_output_mode()`, and `subscribe()`.

- [ ] **Step 1: Write failing API and transactional import tests**

```python
def test_import_with_dangling_reference_rolls_back(client, seeded_project):
    export_url = f"/studio/projects/{seeded_project.id}/export"
    before = client.get(export_url).json()
    broken = {**before, "rules": [{"id": "r", "human_pose_id": "missing", "sequence_id": "s"}]}
    response = client.post("/studio/projects/import", json=broken)
    assert response.status_code == 422
    assert client.get(export_url).json() == before


def test_oversized_import_is_rejected(client):
    response = client.post(
        "/studio/projects/import",
        content=b"x" * (5 * 1024 * 1024 + 1),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413


def test_live_output_defaults_to_simulator(client):
    assert client.get("/studio/output-mode").json() == {"mode": "simulator"}
```

- [ ] **Step 2: Run API tests and confirm they fail**

Run: `uv run pytest backend/tests/studio/test_import_export.py backend/tests/studio/test_studio_api.py -v`
Expected: FAIL with 404 or missing modules.

- [ ] **Step 3: Implement typed schemas and versioned package validation**

```python
class ProjectPackage(BaseModel):
    schema_version: Literal[1]
    project: ProjectPayload
    human_poses: list[HumanPosePayload]
    training_samples: list[PoseSamplePayload]
    robot_poses: list[RobotPosePayload]
    sequences: list[SequencePayload]
    rules: list[BehaviorRulePayload]
    settings: ProjectSettings = ProjectSettings(output_mode="simulator")


def import_package(repo: StudioRepository, package: ProjectPackage) -> str:
    validate_unique_ids(package)
    validate_references(package)
    validate_known_joints(package.robot_poses)
    with repo.transaction() as conn:
        return repo.insert_package(conn, package)
```

Return structured Pydantic errors, cap request bodies at 5 MiB, and never restore `live_robot` from JSON.

- [ ] **Step 4: Implement runtime and routes, then run integration tests**

`StudioRuntime` connects to `ws://localhost:8001/ws/pose`, extracts/classifies each `subjects[].body_landmarks`, updates the trigger engine, resolves the winning rule, runs the sequence player, and broadcasts English events:

```python
StudioEvent(type="recognition", subject_id="person-2", label="Hands up", confidence=0.82)
StudioEvent(type="hold_progress", subject_id="person-2", progress=0.86)
StudioEvent(type="execution_blocked", sequence_id="seq-1", failed_step=1, message="Fall risk detected")
```

Run: `uv run pytest backend/tests/studio/test_import_export.py backend/tests/studio/test_studio_api.py backend/tests/studio/test_runtime.py -v`
Expected: PASS for CRUD, size limits, rollback, event flow, and simulator default.

- [ ] **Step 5: Run backend regression tests and commit**

Run: `uv run pytest backend/tests -q`
Expected: PASS.

```bash
git add backend/app/studio backend/app/api/routes/studio.py backend/app/api/router.py backend/app/main.py backend/app/state.py backend/tests/studio
git commit -m "feat(workflow): add motion studio API and runtime"
```

---

### Task 7: Frontend Test Harness, Types, API Client, Socket, and Skeleton

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `frontend/vite.config.ts`
- Create: `frontend/src/test/setup.ts`
- Create: `frontend/src/studio/types.ts`
- Create: `frontend/src/studio/api.ts`
- Create: `frontend/src/studio/useStudioSocket.ts`
- Create: `frontend/src/studio/FullBodySkeleton.tsx`
- Create: `frontend/src/studio/FullBodySkeleton.test.tsx`
- Create: `frontend/src/studio/useStudioSocket.test.ts`

**Interfaces:**
- Consumes: Task 6 JSON and WebSocket contracts.
- Produces: `studioApi`, `useStudioSocket()`, and `<FullBodySkeleton landmarks={...} />` for Tasks 8 and 9.

- [ ] **Step 1: Add Vitest configuration and failing skeleton tests**

Add scripts and dependencies:

```json
{
  "scripts": {"test": "vitest run"},
  "devDependencies": {
    "@testing-library/jest-dom": "^6.6.3",
    "@testing-library/react": "^16.1.0",
    "@testing-library/user-event": "^14.6.1",
    "jsdom": "^25.0.1",
    "vitest": "^2.1.8"
  }
}
```

```tsx
it('renders torso and both legs', () => {
  render(<FullBodySkeleton landmarks={fullBodyLandmarks()} />)
  expect(screen.getByTestId('bone-left-hip-left-knee')).toBeInTheDocument()
  expect(screen.getByTestId('bone-left-knee-left-ankle')).toBeInTheDocument()
  expect(screen.getByTestId('bone-right-knee-right-ankle')).toBeInTheDocument()
})
```

- [ ] **Step 2: Install dependencies and confirm tests fail**

Run: `cd frontend && npm install`
Expected: lockfile updates.
Run: `cd frontend && npm test -- FullBodySkeleton.test.tsx`
Expected: FAIL because the component is missing.

- [ ] **Step 3: Implement the typed client, reducer, and safe SVG skeleton**

```ts
export type StudioEvent =
  | { type: 'recognition'; subjectId: string; label: string | null; confidence: number }
  | { type: 'hold_progress'; subjectId: string; progress: number }
  | { type: 'execution_started'; sequenceId: string }
  | { type: 'execution_completed'; sequenceId: string }
  | { type: 'execution_blocked'; sequenceId: string; failedStep: number; message: string }

const BONES: readonly [number, number, string][] = [
  [11, 12, 'shoulders'], [11, 13, 'left-upper-arm'], [13, 15, 'left-lower-arm'],
  [12, 14, 'right-upper-arm'], [14, 16, 'right-lower-arm'],
  [11, 23, 'left-torso'], [12, 24, 'right-torso'],
  [23, 24, 'hips'], [23, 25, 'left-hip-left-knee'], [25, 27, 'left-knee-left-ankle'],
  [24, 26, 'right-hip-right-knee'], [26, 28, 'right-knee-right-ankle'],
]
```

Render only finite coordinates; fade low-visibility joints; expose accessible labels and stable `data-testid` bone names.

- [ ] **Step 4: Test reconnect and build behavior**

Test exponential reconnect capped at five seconds, ping handling, and reducer updates without duplicating listeners.
Run: `cd frontend && npm test -- FullBodySkeleton.test.tsx useStudioSocket.test.ts`
Expected: PASS.
Run: `cd frontend && npm run build`
Expected: PASS.

- [ ] **Step 5: Commit the frontend foundation**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vite.config.ts frontend/src/test frontend/src/studio
git commit -m "feat(workflow): add motion studio frontend foundation"
```

---

### Task 8: Block Library, Training, Sequence Editing, and Rule Canvas

**Files:**
- Create: `frontend/src/studio/BlockLibrary.tsx`
- Create: `frontend/src/studio/BlockLibrary.test.tsx`
- Create: `frontend/src/studio/PoseTrainingDialog.tsx`
- Create: `frontend/src/studio/PoseTrainingDialog.test.tsx`
- Create: `frontend/src/studio/SequenceEditor.tsx`
- Create: `frontend/src/studio/SequenceEditor.test.tsx`
- Create: `frontend/src/studio/RuleCanvas.tsx`
- Create: `frontend/src/studio/RuleCanvas.test.tsx`

**Interfaces:**
- Consumes: `studioApi` and types from Task 7.
- Produces: controlled components used by `MotionStudio` in Task 9.

- [ ] **Step 1: Write failing training and editor behavior tests**

```tsx
it('requires three accepted samples before saving', async () => {
  render(<PoseTrainingDialog open api={fakeApi()} />)
  await captureAcceptedSamples(2)
  expect(screen.getByRole('button', { name: 'Save human pose' })).toBeDisabled()
  await captureAcceptedSamples(1)
  expect(screen.getByRole('button', { name: 'Save human pose' })).toBeEnabled()
})


it('reorders sequence steps and keeps timings with their blocks', async () => {
  render(<SequenceEditor steps={threeSteps()} onChange={onChange} />)
  await moveStep('Crouch', 'before', 'Wave')
  expect(onChange).toHaveBeenLastCalledWith([
    expect.objectContaining({ poseName: 'Crouch', holdMs: 1000 }),
    expect.objectContaining({ poseName: 'Wave', holdMs: 800 }),
    expect.objectContaining({ poseName: 'Stand', holdMs: 700 }),
  ])
})
```

- [ ] **Step 2: Run component tests and confirm they fail**

Run: `cd frontend && npm test -- BlockLibrary PoseTrainingDialog SequenceEditor RuleCanvas`
Expected: FAIL because components do not exist.

- [ ] **Step 3: Implement controlled English-only components**

Use native accessible controls and HTML drag/drop with keyboard move-up/move-down alternatives. Validate unique names, `holdMs >= 100`, `transitionMs >= 100`, confidence `0..1`, and cooldown `>= 0` before API calls.

```tsx
<fieldset>
  <legend>Response sequence</legend>
  {steps.map((step, index) => (
    <SequenceStepRow
      key={step.id}
      step={step}
      onMoveUp={() => move(index, index - 1)}
      onMoveDown={() => move(index, index + 1)}
      onTimingChange={(timing) => updateTiming(step.id, timing)}
    />
  ))}
</fieldset>
```

Every user-facing string in these files must be English.

- [ ] **Step 4: Run components and build verification**

Run: `cd frontend && npm test -- BlockLibrary PoseTrainingDialog SequenceEditor RuleCanvas`
Expected: PASS.
Run: `cd frontend && npm run build`
Expected: PASS.

- [ ] **Step 5: Commit the editors**

```bash
git add frontend/src/studio
git commit -m "feat(workflow): add motion block editors"
```

---

### Task 9: Three-column Page, Live Preview, End-to-end Verification, and Documentation

**Files:**
- Create: `frontend/src/studio/LivePreview.tsx`
- Create: `frontend/src/studio/LivePreview.test.tsx`
- Create: `frontend/src/studio/useStudioController.ts`
- Create: `frontend/src/pages/MotionStudio.tsx`
- Create: `frontend/src/pages/MotionStudio.css`
- Create: `frontend/src/pages/MotionStudio.test.tsx`
- Modify: `frontend/src/App.tsx:1-61`
- Modify: `frontend/src/App.css`
- Create: `backend/tests/studio/test_end_to_end.py`
- Modify: `README.md`
- Test: `backend/tests/studio/test_end_to_end.py`
- Test: `frontend/src/pages/MotionStudio.test.tsx`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: user-facing `/motion-studio` route and launcher entry.

- [ ] **Step 1: Write failing page, English-copy, and end-to-end tests**

```tsx
it('defaults to simulator and renders the three columns', async () => {
  render(<MotionStudio />)
  expect(await screen.findByRole('heading', { name: 'Block Library' })).toBeVisible()
  expect(screen.getByRole('heading', { name: 'Rule Canvas' })).toBeVisible()
  expect(screen.getByRole('heading', { name: 'Live Preview' })).toBeVisible()
  expect(screen.getByText('Simulator')).toBeVisible()
  expect(screen.getByRole('switch', { name: 'Live Robot' })).not.toBeChecked()
})


it('contains no CJK production copy', () => {
  const { container } = render(<MotionStudio />)
  expect(container.textContent).not.toMatch(/[\u3400-\u9fff]/)
})
```

```python
@pytest.mark.anyio
async def test_any_person_can_trigger_one_safe_simulator_sequence(studio_harness):
    studio_harness.train("Hands up", samples=hands_up_samples(5))
    studio_harness.bind("Hands up", sequence="Celebrate")
    await studio_harness.feed_frame([unknown_subject("p1"), hands_up_subject("p2")], at=0.0)
    await studio_harness.feed_frame([unknown_subject("p1"), hands_up_subject("p2")], at=0.7)
    assert studio_harness.simulator.played_sequences == ["Celebrate"]
    assert studio_harness.hardware.command_batches == []
```

- [ ] **Step 2: Run page and end-to-end tests and confirm they fail**

Run: `cd frontend && npm test -- MotionStudio LivePreview`
Expected: FAIL because the page is missing.
Run: `uv run pytest backend/tests/studio/test_end_to_end.py -v`
Expected: FAIL until the full harness is wired.

- [ ] **Step 3: Implement the three-column page and live states**

`useStudioController` composes `studioApi` and `useStudioSocket`, owns the active selections and unsaved editor state, and returns `libraryProps`, `ruleProps`, `previewProps`, `connections`, and `outputMode`. Define `StudioHeader` as a private component in `MotionStudio.tsx`; it is not a second application shell.

```tsx
export default function MotionStudio() {
  const studio = useStudioController()
  return (
    <main className="motion-studio">
      <StudioHeader connections={studio.connections} outputMode={studio.outputMode} />
      <div className="motion-studio__columns">
        <BlockLibrary {...studio.libraryProps} />
        <RuleCanvas {...studio.ruleProps} />
        <LivePreview {...studio.previewProps} />
      </div>
    </main>
  )
}
```

Show recognition confidence, subject ID, 0.7-second progress, busy/cooldown, failing step, and English safety messages. Keep `Live Robot` off on first render, reload, import, reconnect, and hardware error.

- [ ] **Step 4: Add the route, docs, and run the full verification matrix**

Add `/motion-studio` to `App.tsx` and a `Motion Studio` launcher button. Document training, composing, previewing, JSON backup, and the explicit live-hardware gate in `README.md`.

Run: `uv run pytest backend/tests -q`
Expected: PASS.
Run: `cd frontend && npm test`
Expected: PASS.
Run: `cd frontend && npm run build`
Expected: PASS.
Run: `uv run ruff check backend/app backend/tests`
Expected: PASS.
Run: `git diff --check`
Expected: no output.

- [ ] **Step 5: Perform a local smoke test and commit**

Start simulator mode, train `Hands up` from five recorded sample frames, create a three-pose `Celebrate` sequence, bind the rule, hold the pose for 0.7 seconds, and confirm:

```text
Recognition: Person 2 · Hands up · ≥ 78%
Safety: Passed
Output: Simulator
Execution: Wave → Crouch → Stand
Hardware commands: 0
```

```bash
git add frontend/src frontend/package.json frontend/package-lock.json backend/tests/studio README.md
git commit -m "feat(workflow): add motion block studio"
```

---

## Final Branch Review

- [ ] Compare the branch with `origin/pr/10` and confirm only Motion Block Studio changes are present.
- [ ] Re-run backend tests, frontend tests, frontend build, Ruff, and `git diff --check` from a clean worktree.
- [ ] Review generated SQLite and exported JSON to confirm no camera images, secrets, or executable SVG content are stored.
- [ ] Confirm all production strings under `frontend/src/studio` and `frontend/src/pages/MotionStudio*` are English.
- [ ] Confirm `Live Robot` is off after fresh start, refresh, import, WebSocket reconnect, and simulated hardware disconnect.
