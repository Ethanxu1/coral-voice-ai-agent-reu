# Tutorial Redesign Proposal

> **Goal:** Rework the tutorial into an interactive, kid-facing workflow that explains *and* lets the child try every major piece of functionality — including the sim manual controls — before they meet the real robot.
>
> **Target audience:** Upper elementary through high school.
> **Date:** 2026-07-20

---

## What's Missing From the Current Tutorial

The current `Tutorial.tsx` has the right bones (Welcome → Explore → Concepts → Ready), but it:

1. Doesn't surface the **manual joint controls** in `RobotViewer` (auto/manual toggle, click a limb, drag to rotate).
2. Doesn't explain the **AI Reasoning Stepper** that the child sees in the real demo.
3. Doesn't introduce **"Follow my movement"** mirroring.
4. Doesn't show the **Saved Poses library / replay** flow.
5. Uses a lot of adult-facing chrome (stage navigator, "Return to stand" dev button) inside the kid view.
6. Has a few confusing concept screens, e.g. the "Intent" concept is scripted but looks like a real classification result.

This proposal fixes those gaps while keeping the parts that already work.

---

## Redesigned Workflow (High Level)

```
[Welcome]
   │
   ▼
[Sim Playground]  ← manual controls + block picker sandbox
   │
   ▼
[Concept 1: Joints & Movement]     ← voice command, see reasoning stepper
[Concept 2: Instructions & Intent] ← live intent classification, approve/reject
[Concept 3: Safety Checks]         ← collision check in action
[Concept 4: Follow My Movement]    ← vision mirroring demo
[Concept 5: Capture & Save a Pose] ← countdown → capture → name → save
   │
   ▼
[Free Practice]   ← full voice loop with reasoning stepper
   │
   ▼
[Readiness Gate]  → go to real robot
```

### Key decisions

- **One linear path.** No branching except "Skip" and "Try again." Kids get a predictable foundation.
- **Try before being told.** Each concept starts with a short interactive action, then a one-sentence explanation.
- **The sim is the star in the tutorial.** Real robot is only at the end.
- **Manual controls get their own screen.** They're fun, visual, and teach "joints" more intuitively than text.

---

## Screen-by-Screen Design

### 1. Welcome

**Purpose:** Friendly entry, set expectation that the child is the teacher.

**Layout:** full-screen, minimal chrome.

```
┌─────────────────────────────────────────────┐
│                                             │
│         [CORAL robot illustration]          │
│                                             │
│   "Hey! I'm CORAL's helper.                 │
│    Today, YOU get to be the robot teacher.  │
│    Let's practice in the simulator first."  │
│                                             │
│        [ Let's explore! ]  [ Skip → ]       │
│                                             │
└─────────────────────────────────────────────┘
```

**Changes from current:**
- Remove the floating stage navigator from this screen (keep it facilitator-only or remove it).
- Single primary CTA: "Let's explore!" instead of "Let's go!" to match the first activity.

---

### 2. Sim Playground — Manual Controls + Block Picker

**Purpose:** Let the child discover that the robot has joints, each joint has limits, and the sim is safe to experiment in.

**Layout:**

```
┌──────────────────────────────────────────────────────────┐
│  SIMULATOR PLAYGROUND                        [Skip →]    │
├─────────────────────────┬────────────────────────────────┤
│                         │  [Agent speech bubble]         │
│   [MuJoCo sim view]     │  "Try clicking a robot arm     │
│   (manual mode: click   │   and dragging to move it.     │
│    a joint → drag the   │   That's a joint!"             │
│    gizmo to rotate)     │                                │
│                         │  ──────────────────────────    │
│                         │  OR build a move block-by-     │
│                         │  block:                        │
│                         │  [Shoulder ▼] [Raise ▼]        │
│                         │  [Execute motion]              │
│                         │                                │
│                         │  [I got it → next concept]     │
└─────────────────────────┴────────────────────────────────┘
```

**Interaction details:**

1. On enter, the `RobotViewer` starts in **manual mode** (not auto).
2. The agent bubble prompts: *"Click an arm or leg, then drag the ring to rotate it."*
3. When a joint is selected, a small label appears near it:
   - joint name in kid words (e.g. "Right elbow")
   - current angle
   - min/max range
4. The block picker from the current "Explore" screen stays on the right as an alternative.
5. A **hint pill** at the bottom of the sim view says:
   > "Tip: Green ring = safe, Yellow = getting close to limit, Red = blocked."
6. "I got it →" advances to Concept 1 once the child has moved at least one joint OR used the block picker once.

**Why:** Manual controls are the most direct way to learn "joints & degrees of freedom." The block picker then shows how voice commands map to the same joints.

---

### 3. Concept 1 — Joints & Movement

**Purpose:** Show that voice commands move the same joints the child just touched.

**Layout:** same two-column as current concept screen.

**Flow:**
1. Agent: *"You just moved my arm by hand. Now try with your voice!"*
2. Large mic button: tap → listen → transcript appears.
3. Suggested prompts as chips: *"raise your right arm"*, *"look up"*, *"bend your left elbow"*.
4. After the command executes, the robot moves in the sim.
5. The **AI Reasoning Stepper** appears for the first time on the right, below the transcript:

```
┌─────────────────────┐
│  ✓ You said         │
│  ✓ Understanding    │
│  ✓ Safety Check     │
│  ▶ Execute          │
└─────────────────────┘
```

6. Agent explains: *"First I figure out what you said, then I check it's safe, then I move."*
7. "Next →" to Concept 2.

**Changes from current:**
- Add reasoning stepper so the child learns the UI pattern before the real demo.
- Use suggested prompt chips instead of requiring the child to guess the exact phrase.

---

### 4. Concept 2 — Instructions & Intent

**Purpose:** Teach that the AI interprets commands and can be corrected.

**Flow:**
1. Agent: *"Sometimes I'm not sure what you mean. Let's see what I guess."*
2. The child taps the mic and says something intentionally ambiguous, e.g. *"move my arm"* (no side specified).
3. The reasoning stepper stops at **Understanding** with a live intent classification:
   > "I think you want to raise CORAL's **LEFT ARM**. Is that right?"
4. Buttons: **[Yes, do it]** **[No, try the right arm]** **[Say it again]**
   - "Yes" proceeds through Safety Check → Execute.
   - "No" re-classifies with the correction (or shows a clarifying question).
   - "Say it again" re-listens.
5. After a successful execution, agent: *"See? I made a guess, and you fixed it. You can always correct me."*

**Changes from current:**
- Use a **real** intent-classifier call (`/classify-intent`) instead of a hard-coded example, so the behavior matches the main demo.
- Provide concrete correction options rather than a generic Yes/No.

---

### 5. Concept 3 — Safety Checks

**Purpose:** Show collision / self-collision checking.

**Flow:**
1. Agent resets the robot to stand.
2. Agent: *"Now let's try a move that isn't safe. Say: 'rotate your right arm into your stomach.'"*
3. Suggested prompt chip with that exact phrase.
4. Child says it (or taps the chip to auto-fill and run).
5. Reasoning stepper reaches **Safety Check** and turns red:
   > "Safety check blocked: CORAL's arm would hit its body. I moved it as far as was safe."
6. Agent: *"My safety checker stopped the move so nothing gets hurt."*
7. "Next →" to Concept 4.

**Changes from current:**
- Integrate with the reasoning stepper.
- Show the actual `safeFraction` / clamped result if the server returns it.

---

### 6. Concept 4 — Follow My Movement

**Purpose:** Introduce vision-based mirroring.

**Layout:** sim panel now also shows the live camera PiP more prominently.

**Flow:**
1. Agent: *"I can also copy the way you move! Stand back so I can see your whole body."*
2. Button: **[Start following]**
3. On press, the robot enters follow mode and mirrors the child's arm/leg positions in near-real-time.
4. A badge appears: *"Mirroring your moves"*.
5. After ~10 seconds, the agent prompts: *"Great! Say 'capture' or tap here to freeze this pose."*
6. Button: **[Capture this pose]** → triggers the capture flow inline (no new screen yet).

**Why include this:** It's a major feature of the real demo and a fun tutorial moment.

---

### 7. Concept 5 — Capture & Save a Pose

**Purpose:** Full end-to-end pose capture: countdown → vision retarget → execute → name → save.

**Flow:**
1. Agent: *"Let's save the pose you were just doing. Hold still…"*
2. Countdown 3-2-1 overlay on the sim panel.
3. Shutter sound + flash.
4. "Reading your pose…" analyzing state.
5. If no full body visible: friendly retry message with a specific tip (e.g. "step back").
6. On success, the sim robot strikes the captured pose.
7. Agent: *"Now give it a name!"*
8. Mic listens for a name; fallback to a default like "My Pose" if empty.
9. "Saved to My Poses!"
10. "Next →" to Free Practice.

**Changes from current:**
- Use the same `mapFeatures` + `saveCurrentPose` flow as `RefinedDemo`.
- Show the captured frame thumbnail.
- Allow retry if pose detection fails.

---

### 8. Free Practice

**Purpose:** Let the child run the full voice loop freely before the real robot.

**Layout:**

```
┌──────────────────────────────────────────────────────────┐
│  FREE PRACTICE                              [I'm ready →]│
├─────────────────────────┬────────────────────────────────┤
│                         │  [AI Reasoning Stepper]        │
│   [MuJoCo sim view]     │  1 ✓ You said                  │
│   (auto mode)           │  2 ✓ Understanding             │
│                         │  3 ✓ Safety Check              │
│                         │  4 ○ Clarification             │
│                         │  5 ▶ Execute                   │
│                         │                                │
│                         │  [Mic button]                  │
│                         │  [Suggested chips]             │
│                         │  [Chat transcript]             │
└─────────────────────────┴────────────────────────────────┘
```

**Interaction details:**
1. This is a lightweight, tutorial-only version of the `RefinedDemo` voice loop.
2. Suggested chips:
   - "Raise your left arm"
   - "Capture my pose"
   - "Do a wave"
   - "What can you do?"
3. The reasoning stepper is always visible on the right.
4. After at least one successful command, the "I'm ready →" button becomes enabled.
5. "I'm ready" advances to the Readiness Gate.

**Why:** This is where the child practices the *exact* UI they'll see with the real robot.

---

### 9. Readiness Gate

**Purpose:** Celebration and transition.

**Layout:** full-screen, minimal chrome, confetti.

```
┌─────────────────────────────────────────────┐
│                                             │
│   ★  You did it!  ★                        │
│                                             │
│   [Robot in celebratory pose]               │
│                                             │
│   "You taught CORAL a lot in the simulator. │
│    Ready to try with the real robot?"       │
│                                             │
│        [ Meet the real CORAL! ]             │
│                                             │
└─────────────────────────────────────────────┘
```

**Changes from current:**
- Keep the celebratory pose but make sure the robot actually animates a small wave.
- Single large CTA.
- Navigates to `/home` (RefinedDemo) with `fromApp: true`.

---

## New / Reused Components

| Component | Source | Notes |
|---|---|---|
| `RobotViewer` (manual mode) | existing | Start in manual mode for Sim Playground; auto mode elsewhere. |
| `AIReasoningStepper` | **new** | Vertical stepper: You said → Understanding → Safety Check → Clarification → Execute. Used in concepts, free practice, and ideally mirrored in `RefinedDemo`. |
| `MicOrb` | existing | Reuse the pulsing orb from `Tutorial.tsx` / `MoveMate.tsx`. |
| `SuggestedChip` | **new small component** | Kid-friendly prompt chips. |
| `PoseThumbnail` | existing pattern | Reuse the captured-frame thumbnail from `RefinedDemo`. |
| `Confetti` | existing | Keep for Readiness Gate. |

---

## Component: AI Reasoning Stepper (detailed)

A vertical list on the right panel.

```
┌─────────────────────────────────┐
│ 1  ✓  You said                  │
│     "raise your left arm"       │
├─────────────────────────────────┤
│ 2  ✓  Understanding             │
│     I think: raise LEFT ARM     │
├─────────────────────────────────┤
│ 3  ✗  Safety Check              │
│     Arm would hit body.         │
│     [Try again]                 │
├─────────────────────────────────┤
│ 4  —  Clarification (skipped)   │
├─────────────────────────────────┤
│ 5  ○  Execute                   │
└─────────────────────────────────┘
```

**States:**
- `upcoming` — greyed out
- `active` — accent color, subtle spinner
- `success` — green checkmark
- `blocked` — red X + reason + action button
- `skipped` — grey dash

**Animation:** 200ms expand/collapse, checkmark pop, blocked-state gentle shake.

---

## Suggested Prompts / Kid-Friendly Copy

Use plain language and consistent robot name (CORAL).

- "raise your right arm"
- "bend your left elbow"
- "look up"
- "wave hello"
- "follow my movement"
- "capture my pose"
- "save this as Superhero"
- "what can you do?"

---

## Facilitator / Dev View (optional, hidden by default)

A small toggle (e.g. press `?`) reveals:

- Stage navigator to jump to any screen.
- "Return to stand" button.
- Session log (transcripts, intent results).

This replaces the always-visible stage navigator in the current tutorial, which is confusing for kids.

---

## Open Questions

1. **Should manual controls also allow slider input?** Dragging the gizmo is discoverable but can be fiddly; a simple slider per joint could be a fallback.
2. **Should Free Practice support text input too?** The real demo is voice-first; keep it voice-only for consistency unless accessibility requires text.
3. **Should the tutorial auto-launch every session?** Existing design says yes with a facilitator toggle to disable.

---

## Implementation Phases (if doing this incrementally)

1. **Phase A:** Add `AIReasoningStepper` component; integrate into existing concepts.
2. **Phase B:** Rewrite Sim Playground to feature manual controls + block picker.
3. **Phase C:** Add Concept 4 (Follow) and Concept 5 (Capture/Save) using real APIs.
4. **Phase D:** Add Free Practice screen.
5. **Phase E:** Polish animations, remove dev chrome from kid view, facilitator toggle.
