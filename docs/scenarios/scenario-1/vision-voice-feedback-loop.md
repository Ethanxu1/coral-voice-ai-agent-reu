# Scenario: Vision + Voice User Feedback Loop (Post-Integration)

## 3. Annotated Transcript

Same target pose as the pre-vision scenario. Each turn shows the trigger (voice or stability event), which agent processed it, the payload passed forward, and the resulting waypoint or memory mutation.

### Turn 1 — user strikes a pose

The user stands in front of the camera and holds a superhero pose: right arm forward at ~90°, left arm out to the side, chin slightly up. After ~1.2 seconds the landmark-difference moving average drops below the stability threshold.

**Frame-selection agent fires:**

```json
{
  "snapshot_id": "snap-001",
  "stable": true,
  "landmarks_summary": {
    "right_shoulder_flexion_deg": 88,
    "left_shoulder_abduction_deg": 92,
    "head_pitch_deg": 18,
    "head_yaw_deg": 2
  },
  "raw_landmark_count": 33
}
```

Only the summary is forwarded to the merging agent. The full 33-landmark array stays in the vision service. **This is the key bandwidth choice from the Jun 17 notes:** the merger never sees the raw stream.

**Merging agent → final waypoints:**

```json
{
  "verbal_response": "I see your pose. Let me try to match it.",
  "waypoints": [
    {
      "primitives": ["right_arm_forward", "left_arm_out", "head_tilt"],
      "angle_per_primitive": {
        "right_arm_forward": 88,
        "left_arm_out": 92,
        "head_tilt": 18
      },
      "direction_per_primitive": {
        "head_tilt": "up"
      },
      "speed": 1.0
    }
  ]
}
```

> Note: `angle_per_primitive` is a small extension of the existing waypoint shape, needed because a single pose-mimicry waypoint now contains primitives whose target angles differ. The voice agent's existing `angle` field stays unchanged — the merger only emits this richer form when sourcing from a snapshot.

**Joint deltas:** `r_sho_pitch: 88°`, `l_sho_roll: 92°`, `head_tilt: 18°` — all set in a single waypoint.
**Memory mutation:** `snap-001` becomes a new root node in the tree-structured memory.

```
snap-001 (right_arm_forward=88, left_arm_out=92, head_tilt=18)
```

**Friction removed:** Compare to the pre-vision turns 1–3, which took three sequential dialogue exchanges to specify the same multi-joint pose. Here it's one event.

---

### Turn 2 — verbal correction (grounded in shared visual reference)

> **user** "your right arm is too high, lower it a little"

The user can see this on screen — the robot's right arm is at 88°, the user's actual arm in the live skeleton overlay is closer to 80°. They both have the same visual reference now.

**Voice agent → verbal delta:**

```json
{
  "intent": "adjust",
  "target_primitive": "right_arm_forward",
  "delta_deg": -8,
  "verbal_response": "Lowering my right arm a little.",
  "rationale": "User used 'a little' modifier; CURRENT_STATE shows r_sho_pitch=88. Applying -8 deg."
}
```

The voice agent does **not** issue final waypoints — it produces a *delta intent* and hands off to the merger.

**Merging agent** looks up the current snapshot parent (`snap-001`) and applies the delta:

```json
{
  "verbal_response": "Lowering my right arm a little.",
  "waypoints": [
    {
      "primitives": ["right_arm_forward"],
      "angle": 80,
      "direction": null,
      "speed": 1.0
    }
  ]
}
```

**Joint deltas:** `r_sho_pitch: 80°`.
**Memory mutation:** new child node attached under `snap-001`:

```
snap-001
  +-- edit-001 (right_arm_forward: 88 -> 80, reason: "too high")
```

**Friction removed:** "A little" is now grounded — both the user and the merging agent share `snap-001` as the reference for what's being adjusted *from*.

---

### Turn 3 — "match me" correction (cross-modal)

> **user** "match my arm exactly — look at the screen"

The user holds their right arm steady. The vision service is still streaming. Stability threshold trips on the user's *arm region alone*.

**Frame-selection agent** emits a focused snapshot — same shape as `snap-001` but scoped to a specific joint cluster:

```json
{
  "snapshot_id": "snap-002",
  "parent": "snap-001",
  "stable": true,
  "scope": ["right_arm_forward"],
  "landmarks_summary": {
    "right_shoulder_flexion_deg": 76
  }
}
```

**Voice agent** classifies the intent and forwards control to the merger:

```json
{
  "intent": "mimic_scoped",
  "scope": ["right_arm_forward"],
  "verbal_response": "Matching my right arm to yours."
}
```

**Merging agent** combines the two:

```json
{
  "verbal_response": "Matching my right arm to yours.",
  "waypoints": [
    {
      "primitives": ["right_arm_forward"],
      "angle": 76,
      "direction": null,
      "speed": 1.0
    }
  ]
}
```

**Joint deltas:** `r_sho_pitch: 76°`.
**Memory mutation:**

```
snap-001
  +-- edit-001 (right_arm_forward: 88 -> 80)
  +-- snap-002 (scoped: right_arm_forward=76, parent=snap-001)
```

**Friction removed (this is the central one):** The pre-vision Turn 4 — *"more like this"* — was unrunnable without a shared reference. Here it executes cleanly because the camera *is* the reference.

---

### Turn 4 — refined verbal correction off the latest snapshot

> **user** "now raise it by 5"

**Voice agent → verbal delta:**

```json
{
  "intent": "adjust",
  "target_primitive": "right_arm_forward",
  "delta_deg": 5,
  "verbal_response": "Raising my right arm by 5 degrees."
}
```

**Merging agent** resolves the delta against the most recent node in the active branch (`snap-002`, not `edit-001`):

```json
{
  "verbal_response": "Raising my right arm by 5 degrees.",
  "waypoints": [
    {
      "primitives": ["right_arm_forward"],
      "angle": 81,
      "direction": null,
      "speed": 1.0
    }
  ]
}
```

**Joint deltas:** `r_sho_pitch: 81°`.
**Memory mutation:**

```
snap-001
  +-- edit-001 (right_arm_forward: 88 -> 80)
  +-- snap-002 (right_arm_forward=76)
       +-- edit-002 (right_arm_forward: 76 -> 81)
```

---

### Turn 5 — undo "back to before my tweaks"

> **user** "go back to before I started fixing it"

This is the failure mode from Turn 7 of the pre-vision scenario: the user wants to revert *to a snapshot*, not undo one servo command.

**Voice agent → intent:**

```json
{
  "intent": "revert_to_snapshot",
  "anchor": "most_recent_root_snapshot",
  "verbal_response": "Going back to your first pose."
}
```

**Merging agent** finds the active branch's root snapshot (`snap-001`) and reissues it. Subsequent corrections become a new sibling branch off `snap-001` rather than continuing under `snap-002`:

```json
{
  "verbal_response": "Going back to your first pose.",
  "waypoints": [
    {
      "primitives": ["right_arm_forward", "left_arm_out", "head_tilt"],
      "angle_per_primitive": {
        "right_arm_forward": 88,
        "left_arm_out": 92,
        "head_tilt": 18
      },
      "direction_per_primitive": {
        "head_tilt": "up"
      },
      "speed": 1.0
    }
  ]
}
```

**Friction removed:** Undo unit is now a **conceptual checkpoint** (the snapshot) rather than a servo command. The pre-vision version of "go back" could only revert one keyframe at a time.

---

### Turn 6 — multi-modal correction (visible feedback closes the loop)

> **user** "your left arm is a tiny bit too far back"

The voice agent infers `left_arm_out` from the active branch. The user doesn't need to say "left arm" again because the merger's tree memory has it as a recent edited joint.

The merger considers issuing a small negative delta but instead asks the frame-selection agent to confirm against the current camera frame. Frame-selection agent reports the user's `left_shoulder_abduction_deg = 84`, robot is at 92. Delta inferred: `-8`.

```json
{
  "verbal_response": "Pulling my left arm forward a bit. How's that?",
  "waypoints": [
    {
      "primitives": ["left_arm_out"],
      "angle": 84,
      "direction": null,
      "speed": 1.0
    }
  ]
}
```

**Memory mutation:**

```
snap-001
  +-- edit-001 (right_arm_forward: 88 -> 80)
  +-- snap-002 (right_arm_forward=76)
  |     +-- edit-002 (right_arm_forward: 76 -> 81)
  +-- edit-003 (left_arm_out: 92 -> 84, source: cross-checked with camera)
```

The "tiny bit" modifier was ambiguous on its own — but with the camera available as a tiebreaker, the merger picked the user's actual arm angle instead of guessing a fixed delta. This is the cross-modal grounding the voice-only loop lacked.

---

## 4. Distributed-Input Stress Test

The same scenario as Section 4 of the pre-vision doc: two corrections arriving close together, the second partially superseding the first.

### Turn 7 — first correction dispatched

> **user** "lower your left arm by 20"

**Voice agent:**

```json
{
  "intent": "adjust",
  "target_primitive": "left_arm_out",
  "delta_deg": -20,
  "verbal_response": "Lowering my left arm by 20."
}
```

The merging agent **does not commit immediately**. It places a *pending edit* node on the tree:

```
... (prior tree) ...
  +-- edit-004-pending (left_arm_out: 84 -> 64, in_flight)
```

It dispatches the waypoint to the sim controller — interpolation begins.

### Turn 8 — superseding correction arrives mid-execution

> **user** "wait, by 30 instead"

**Voice agent:**

```json
{
  "intent": "adjust",
  "target_primitive": "left_arm_out",
  "delta_deg": -30,
  "supersedes": "edit-004-pending",
  "verbal_response": "Adjusting to 30 instead."
}
```

The merging agent sees the `supersedes` field and the matching pending edit on the tree. It:

1. Asks the robot controller to **cancel the in-flight interpolation** at its current position (a hook that does not exist today but is small to add — `RobotController` only needs an `abort()` method).
2. Computes the new target relative to the **original anchor** (`84`), not the in-progress value: `84 - 30 = 54`.
3. Replaces `edit-004-pending` with a single committed edit:

```
... (prior tree) ...
  +-- edit-004 (left_arm_out: 84 -> 54, supersedes pending edit-004)
```

1. Issues one new waypoint:

```json
{
  "verbal_response": "Adjusting to 30 instead.",
  "waypoints": [
    {
      "primitives": ["left_arm_out"],
      "angle": 54,
      "direction": null,
      "speed": 1.0
    }
  ]
}
```

**Where this beats the pre-vision behavior:**

- The robot does **not** first overshoot to 64° and then bounce to 54°. It interpolates directly to 54°.
- The action-history tree records the *intent* (single adjustment, final value 54°), not the mechanical sequence of two commands. Future "what did you do?" queries see one edit, not two.
- This generalizes to any number of in-flight corrections (e.g. voice + GUI + a second user) because superseding is keyed on the tree node, not on the order of arrival.

---

## 5. Open Questions / Things to Validate Empirically

Items that are still unresolved and will be settled by running the scenarios above against the real system.

1. **Stability threshold tuning.** Scott's point-difference threshold is the dial that controls how many snapshots fire. Too tight: pose mimicry never triggers. Too loose: snapshots fire mid-motion and the merger gets noise. Per the Jun 17 notes ("test basic numbers first"), start with a fixed threshold and iterate.
2. **Latency budget per agent.** The three-agent decomposition adds round trips. Acceptable end-to-end latency for the user is roughly 1–2 seconds from utterance to motion start. The voice agent has been on `gpt-4o-mini` for that reason; DK recommended moving to the latest model. The frame-selection agent should stay on a small heuristic / lightweight model to absorb that budget.
3. **Hallucination on landmark payloads.** Open question from the Jun 17 notes: can the merging agent reliably convert summarized landmark data into primitive angles without hallucinating? Mitigation already planned: context augmentation with examples of (landmark summary, expected waypoint) pairs.
4. **Cancellation semantics.** The supersede flow in Section 4 requires `RobotController.abort()`. Trivial in sim (kill the interpolation thread); needs a corresponding stop command for the hardware path.
5. **Tree memory eviction.** The current `HierarchicalMemory` ages out to mid-term summaries by count. A tree-shaped memory needs a different eviction policy — likely "compress subtrees older than N turns into a single summary node," so the root snapshot stays addressable for "go back" even after many edits.
6. **Graceful degradation when vision is occluded.** Per the Jun 17 notes, MediaPipe lacks memory of previous arm positions when the view is blocked. The merging agent should detect a stale `landmarks_summary` (no fresh snapshot for several seconds) and fall back to voice-only correction with an explicit signal to the user.
