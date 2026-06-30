### Turn 1 — opening request (ambiguous)

> **user** "lift one up forward and one arm to the side"

```json
{
  "verbal_response": "Sure! Which arm should I put forward and which one to the side?",
  "waypoints": []
}
```

---

### Turn 2 — disambiguated

> **user** "Right arm forward, left arm to the side."

```json
{
  "verbal_response": "Putting my right arm forward and my left arm out.",
  "waypoints": [
    {
      "primitives": ["right_arm_forward", "left_arm_out"],
      "angle": null,
      "direction": null,
      "speed": 1.0
    }
  ]
}
```

**Joint deltas after execution:** `r_sho_pitch: 90°`, `l_sho_roll: 90°` (primitive defaults applied because `angle` was `null`).
**Memory:** short-term now has 2 exchanges; action history adds 1 row containing both primitives.
**Note:** Two primitives operate on disjoint joints (`r_sho_pitch` vs. `l_sho_roll`), so packing them into a single waypoint is legal under the prompt's parallel-track rule.

---

### Turn 3 — head pose, separate turn (multi-joint poses cost turns)

> **user** "Now tilt your head up."

```json
{
  "verbal_response": "Tilting my head up.",
  "waypoints": [
    {
      "primitives": ["head_tilt"],
      "angle": null,
      "direction": "up",
      "speed": 1.0
    }
  ]
}
```

**Joint deltas after execution:** `head_tilt: 15°` (primitive default).
**Memory:** 3 exchanges.
**Friction:** This is turn 3 to set up *one* multi-joint pose. With six joints involved in a complex pose, the user could spend a full minute just specifying it.

---

### Turn 4 — vague visual correction (cannot be grounded)

> **user** "No, more like *this* — chin higher, like you're looking at the sky."

```json
{
  "verbal_response": "I'll tilt my head up a bit more — does this look right?",
  "waypoints": [
    {
      "primitives": ["head_tilt"],
      "angle": 25,
      "direction": "up",
      "speed": 1.0
    }
  ]
}
```

**Joint deltas:** `head_tilt: 25°` (relative bump: prior 15° + ~10°).
**Memory:** action history row references same primitive as turn 3, so the planner can keep tracking which joint is being adjusted.
**Friction (the central one):** "like *this*" carries no information for the agent. The system is **guessing** at the user's intent and confirming verbally. There is no shared frame of reference.

---

### Turn 5 — relative adjustment using `CURRENT_STATE`

> **user** "Raise your right arm by 10 degrees."

`CURRENT_STATE` passed to the LLM includes `r_sho_pitch: 90.0`.

```json
{
  "verbal_response": "Raising my right arm to 100 degrees.",
  "waypoints": [
    {
      "primitives": ["right_arm_forward"],
      "angle": 100,
      "direction": null,
      "speed": 1.0
    }
  ]
}
```

**Joint deltas:** `r_sho_pitch: 100°`. Within the 119° max for the primitive — `validation.py` does not clamp.
**Note:** Exercises the "Relative angle adjustments" branch of `router.md` — `new_angle = current_degrees + 10` using the current state explicitly.

---

### Turn 6 — speed change

> **user** "Wait, can you do that slower? Lower it back down by 10."

```json
{
  "verbal_response": "Lowering my right arm back to 90 degrees, more slowly.",
  "waypoints": [
    {
      "primitives": ["right_arm_forward"],
      "angle": 90,
      "direction": null,
      "speed": 0.5
    }
  ]
}
```

**Joint deltas:** `r_sho_pitch: 90°`, executed over ~2000 ms instead of 1000 ms (per `angle_utils.py`: `duration_ms = 1000 / speed`).
**Memory:** short-term still has the full turn-5/turn-6 pair; the planner uses turn 5's "right arm" implicitly — no re-disambiguation needed.

---

### Turn 7 — undo / rollback

> **user** "Actually, go back to where you were before."

```json
{
  "verbal_response": "Rolling back to the previous pose.",
  "waypoints": [
    {
      "primitives": ["right_arm_forward"],
      "angle": 100,
      "direction": null,
      "speed": 1.0
    }
  ]
}
```

**Joint deltas:** `r_sho_pitch: 100°` again.
**Note:** "Go back" is caught by the rollback regex in `state.py` → `StateManager` restores the checkpoint from before turn 6 by interpolating over 30 steps. The router does not have to reason about the rollback itself; it's a different code path.
**Friction:** The undo unit is **one servo command**, not "the last *conceptual* edit." If a user had made three small adjustments to the same arm, "go back" only reverts one of them.

---

### Turn 8 — arm inferred from history

> **user** "A bit higher."

The router sees in short-term memory that the last arm motion was on the right arm. It does not re-ask.

```json
{
  "verbal_response": "Raising my right arm to 110 degrees.",
  "waypoints": [
    {
      "primitives": ["right_arm_forward"],
      "angle": 110,
      "direction": null,
      "speed": 1.0
    }
  ]
}
```

**Joint deltas:** `r_sho_pitch: 110°`.
**Memory observation:** This works because the most recent action-history rows are still in the **short-term window**. Once the conversation exceeds 6 exchanges, this turn will fall back to mid-term *summaries* — which may or may not preserve "the last arm was right."

---

### Turn 9 — out-of-range, validation clamps silently

> **user** "Higher!"

```json
{
  "verbal_response": "Raising my right arm to 125 degrees.",
  "waypoints": [
    {
      "primitives": ["right_arm_forward"],
      "angle": 125,
      "direction": null,
      "speed": 1.0
    }
  ]
}
```

`validation.py` clamps `r_sho_pitch` to 119° (the primitive max). The LLM does not know it was clamped unless we feed that fact into the next `CURRENT_STATE`.
**Friction:** From the user's perspective the robot "stopped responding" — there's no surfaced signal that the limit was hit. Without vision, the user cannot tell if the arm visibly moved.

---

### Turn 10 — reset

> **user** "Okay, start over."

```json
{
  "verbal_response": "Resetting to neutral.",
  "waypoints": [
    {
      "primitives": ["neutral"],
      "angle": null,
      "direction": null,
      "speed": 1.0
    }
  ]
}
```

**Joint deltas:** all joints → 0°.
