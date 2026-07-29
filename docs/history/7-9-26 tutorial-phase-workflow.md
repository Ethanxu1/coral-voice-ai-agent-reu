# Tutorial Phase Workflow

> **Status:** Active design — updated Jul 9, 2026 from meeting with Scott and Xinyue.
>
> **Goal:** An interactive tutorial that teaches children basic robot concepts (joints, degrees of freedom, safety, AI reasoning) in MuJoCo simulation *before* they interact with the physical robot. This is the onboarding gate for non-robotics audiences.
>
> **Target audience:** Upper elementary through high school. Avoid lower elementary — voice recognition and comprehension challenges have been documented in prior summer camp experience.

---

## High-Level Pipeline

```
[App Launch]
      |
      v
[Tutorial Mode auto-launches]
   |         |
[Skip]    [Start Tutorial]
   |         |
   |    [Phase 1: Entry & Framing]
   |         |
   |    [Phase 2: Sim Introduction (avatar or MuJoCo)]
   |         |
   |    [Phase 3: Guided Concepts — Linear (voice + safety)]
   |         |
   |    [Phase 4: Readiness Check]
   |         |
   +---->[Voice Interaction — Real Robot]
              |
         [Intent Classifier (LLM) → shows interpretation]
              |
         [User confirms / clarifies]
              |
         [Motion Planner → Collision Sim]
              |
         [User approves → Execute on Robot]
              |
         [Pose Capture / Save Workflow]
         [Adaptive Free-Play (post-tutorial)]
```

> **Design decision (Jul 9):** The adaptive simulator environment (previously Phase 3b) is merged into the **post-tutorial phase** — it runs after the child transitions to real robot interaction, not as a required tutorial step. This simplifies the tutorial gate while preserving freeplay value.

---

## Launch & Entry Trigger

- **Auto-launches** at application start every time.
- A **Skip button** is always visible — no child is forced through it.
- A **facilitator toggle** (accessible via settings or admin panel) can disable auto-launch for returning users or controlled study conditions.
- Session state should track whether the tutorial was completed or skipped, for research logging.

---

## Phase 1: Entry & Framing

**Goal:** Welcome the child, set expectations, and frame the activity as *them* teaching the robot — not the other way around.

### Dialogue Agent Script (sample)

The agent uses warm, conversational tone — not robotic commands:

```
Agent: "Hey! I'm CORAL's helper. Today, YOU get to be the robot teacher.
        Before we meet the real robot, let's practice in here first.
        Are you ready to start?"

[Child responds: yes / nod / clicks Ready]

Agent: "Great! First, let's learn a little about how robots move.
        Don't worry — I'll guide you the whole way."
```

**Design principle:** The agent guides step-by-step using natural dialogue. The child should feel like they're in a conversation, not filling out a form. (Xiaoyi's proposal from meeting.)

---

## Phase 2: Simulation Introduction

**Goal:** Show the child how the robot's joints work in simulation — experiment freely without fear of hurting the robot or themselves.

### Simulation backend

- **Backend:** MuJoCo running as a subprocess, same as the existing collision checker infrastructure.
- **Frontend display:** Stream MuJoCo render frames into the React UI via the existing FastAPI server — add a `/sim` websocket or MJPEG endpoint alongside the existing `/ws` connection.
- **Mode flag:** The agent server runs in `tutorial_mode=True`, which routes all commands to MuJoCo instead of the real robot HTTP/ROS server. No changes to the LLM or primitives layer — the same pipeline runs, just with a different execution target.

### Limb highlighting — open design question

> **Raised Jul 9:** MuJoCo may not be flexible enough to visually highlight individual limbs during the tutorial. An **avatar-based alternative** (e.g., a 2D or stylized 3D character) is under consideration for Phase 2 specifically, where highlighting is most critical for concept teaching.

Current options:

| Option | Pros | Cons |
|---|---|---|
| MuJoCo with shader overlay | Same model as collision checker, no extra asset | Highlighting may be limited or visually unclear |
| Avatar-based (2D/3D character) | Clear, friendly visuals; easy joint highlight | Separate asset to build/maintain; decoupled from real robot model |
| Hybrid: avatar for tutorial, MuJoCo for sim play | Best of both | Most work |

**Recommendation:** Prototype MuJoCo highlighting first. If it isn't legible to kids at a glance, switch Phase 2 to avatar — keep MuJoCo for the sim playground (Screen 3) where highlighting isn't the focus.

### What the simulation displays

- The robot's full joint structure: shoulders, elbows, hands, torso, hips
- Real-time joint angle visualization (highlight the active joint — subject to highlighting feasibility above)
- Safety buffer zone rendered as a colored proximity indicator (green → yellow → red as limits approach)

### Structured block interaction model

Avoid fully directive *or* fully freestyle — per the AIUD paper Shiyan referenced, the sweet spot is required parameters per block with creative freedom within each:

| Block | Required parameter | Child's freedom |
|---|---|---|
| Pick a body part | Which joint (shoulder / elbow / wrist / hip) | Which side, how much |
| Set direction | Raise / lower / extend / bend | Speed, intensity |
| Confirm + simulate | Safety check result shown | Try again or accept |

The LLM fills in sensible defaults for anything the child doesn't specify, and narrates what it chose and why.

---

## Phase 3: Guided Concepts — Voice, Workflow, and Safety

**Scope (updated Jul 9):** This phase now explicitly covers voice commands, the full interaction workflow, and safety checking — not just joint concepts. Scott's step-based demo flow (voice command → fix pose → name pose) is incorporated here alongside the conceptual content.

### 3A — Linear Phase (fixed order, teaches the basics)

All children go through these concepts in order. Each should take ~2 minutes max. The agent does not branch or skip — this ensures every child has the same conceptual foundation.

#### Concept 1: Joints & Degrees of Freedom

- Highlight one joint at a time on the MuJoCo model
- Child gives a voice command, watches the result in sim
- Agent: *"Robots only bend where they have joints — just like your elbow! Try moving CORAL's shoulder."*

#### Concept 2: Instructions & Intent (AI Literacy)

- Agent deliberately picks an ambiguous command or the child naturally says something unclear
- Agent surfaces its interpretation: *"I think you want to raise the left arm — is that right?"*
- If wrong, child corrects it. **Key lesson:** the AI is making a guess, not reading minds, and you can fix it.

#### Concept 3: Safety Checks

- Child attempts (or agent demonstrates) a command that would cause a collision
- Safety check triggers — robot does not move, system explains why using the progress UI (see Phase 5)
- Agent: *"Oops! CORAL's arm would bump into its own body there. Let's try a smaller angle."*

#### Concept 4: Full Workflow — Voice Command to Saved Pose

- Walk through one complete cycle: voice command → intent shown → safety check → sim executes → name and save pose
- Mirrors Scott's demo flow (voice commands to fix pose, naming poses)
- Agent narrates each step as it appears in the AI Reasoning Stepper
- This is the direct bridge into what they'll do with the real robot

> **Note:** The adaptive free-play phase (previously 3B) has been moved to **post-tutorial** (after real robot transition). The tutorial now ends at the readiness check after completing the linear phase.

---

---

## Voice Command Pipeline

> **Decision (Jul 9):** The **two-step LLM pipeline** (intent classifier + motion planner) is the chosen approach. Regex matching was considered but rejected — it introduces too many edge cases, especially for non-literal child speech (e.g., "make a happy move").

### Why not regex

- Kids don't speak directly to commands — Xinyue flagged phrases like "make a happy move" that regex can't handle
- Edge case handling grows unbounded
- LLM fallback becomes the real workhorse anyway

### Chosen pipeline: Intent Classifier → Motion Planner

```
[Child speaks]
      |
      v (≤5 sec)
[Step 1: Intent Classifier (LLM)]
   Outputs transparent, user-visible interpretation:
   "I think you want to raise CORAL's left arm."
      |
      v
[User confirms / asks why]
   → If wrong: debugging agent explains and re-classifies
   → If right: proceed
      |
      v
[Step 2: Motion Planner (LLM or structured output)]
   Generates joint angles / motion primitive
      |
      v
[Visual collision simulation runs in parallel]
      |
      v
[User approves simulation preview]
      |
      v
[Execute on physical robot]
      |
      v
[Optionally save pose]
```

### Latency strategy

The two-step pipeline was previously removed due to latency. The approach to mask it:

- Intent classifier result appears **immediately** (≤5 sec) — child reads and confirms while the motion planner runs in parallel
- Safety check collision sim runs **concurrently** with user confirmation, not sequentially after
- The AI Reasoning Stepper UI makes wait time feel like progress, not lag

### Clarification handling

If the intent classifier is uncertain:

- It surfaces its best guess with a confirm prompt rather than asking an open-ended question
- A debugging agent can explain *why* it interpreted the command a specific way
- Child can correct or re-speak; the classifier re-runs

---

## Phase 4: Readiness Check & Transition

**Goal:** Confirm the child is ready, build confidence, then hand off to the real robot.

### Readiness gate

Complete **one** of:

- One successful end-to-end simulated command (voice → intent → safety pass → sim executes)
- Facilitator clicks "Mark as Ready" in admin view
- Child clicks "I'm ready!" themselves (always available after linear phase completes)

### Transition script

```
Agent: "You're a natural teacher! The real CORAL robot is ready for you now.
        Remember — you're still in charge. Tell me what you want CORAL to do,
        and we'll figure it out together."
```

---

## Phase 5: AI Reasoning Progress UI

This UI pattern applies both during the tutorial and during real robot interaction. It replaces the idea of multiple simultaneous panels with a **sequential step progress indicator** — each step lights up one at a time as the agent resolves it.

### Visual design concept

```
[ Your command ]  -->  [ Understanding ]  -->  [ Safety Check ]  -->  [ Clarification? ]  -->  [ Execute ]
       ✓                    spinner...               ✓                    (skipped)               ▶
```

- Steps are shown as a horizontal progress track (like a stepper component)
- Only the **active step** is expanded — shows detail, explanation, or a prompt
- Completed steps collapse to a checkmark with a one-line summary
- Skipped steps (e.g., no clarification needed) are greyed out
- If a step fails (safety blocked), it shows red with an explanation and a "Try again" action

### Step breakdown

| Step | What the child sees |
|---|---|
| **Your command** | Transcript of what they said, shown immediately |
| **Understanding** | What the LLM interpreted — joint, direction, magnitude — with a confirm prompt |
| **Safety Check** | MuJoCo collision sim result — green pass or red block with reason |
| **Clarification** | Only appears if LLM needs more info — phrased as a natural question |
| **Execute** | Preview of what's about to happen, then a Go button (or auto-fires after 2s) |

### Why this design

- Transparent without overwhelming — children see the full reasoning but one piece at a time
- Teaches AI literacy passively — they naturally learn what the system does at each step
- Errors are educational rather than dead ends — the progress bar shows exactly where and why something stopped

---

## Multiple Pose Captures for Accuracy

Per Xiaoyi's suggestion — capture the same pose 3 times and use the best or centroid to reduce noise from body sway.

- **UX framing:** Frame it as a mini-game — *"Let's try that pose 3 times and pick your best one!"*
- **Implementation:** Easy technically (Dr. Gao confirmed); the challenge is keeping the workflow feeling fast
- **Recommendation:** Default to 3 captures in tutorial (teaches the concept), allow 1-capture fast mode in real interaction if the child explicitly asks to skip

---

---

## UI Design Considerations

> **Display context assumption:** Designed for a **large-screen display** (monitor or TV) viewed from ~1–3 feet away by one child at a time, with a facilitator nearby. If the target is a tablet or shared classroom screen, layout densities and tap target sizes will need revisiting.

---

### Screen Inventory

Each distinct view the child encounters, in order:

| Screen | When it appears |
|---|---|
| **1. Welcome / Launch** | App start — tutorial auto-launches |
| **2. Concept Stage** | Each of the 4 linear concepts (reuses same layout, content swaps) |
| **3. Sim Playground** | Adaptive free-play after linear phase |
| **4. Readiness Gate** | After adaptive phase, before real robot |
| **5. Main Interaction** | Real robot session — shares the progress stepper from tutorial |

---

### Screen 1 — Welcome / Launch

**Purpose:** Orient the child, offer skip.

**Layout:**

```
┌─────────────────────────────────────────────┐
│                                             │
│         [CORAL robot illustration]          │
│                                             │
│     "Hey! I'm CORAL's helper.               │
│      Today, YOU get to be the teacher."     │
│                                             │
│         [ Let's go! ]   [ Skip → ]         │
│                                             │
└─────────────────────────────────────────────┘
```

**Design notes:**

- Full-bleed background, minimal chrome — this should feel like an experience, not an app
- Robot illustration or idle MuJoCo render in center to immediately establish the character
- Two-button layout: primary CTA ("Let's go!") large and prominent, Skip is present but visually secondary (smaller, right-aligned, lower contrast)
- Agent's greeting text should appear as a speech bubble near the robot, not as plain UI text — reinforces that the robot is talking to them
- No header bar, no navigation — remove all adult UI scaffolding for this screen

---

### Screen 2 — Concept Stage (Linear Phase)

**Purpose:** Teach one concept at a time. Same layout reused for all 4 concepts.

**Layout:**

```
┌──────────────────────────────────────────────────────────┐
│  ● ● ○ ○   Concept 1 of 4: Joints & Movement    [Skip→] │
├─────────────────────────┬────────────────────────────────┤
│                         │                                │
│   [MuJoCo sim view]     │  [Agent speech bubble]         │
│                         │  "Try telling CORAL to raise   │
│   (joint highlighted    │   its left arm!"               │
│    in active color)     │                                │
│                         │  ──────────────────────        │
│                         │  [Mic button — pulse anim]     │
│                         │                                │
│                         │  [Transcript of what you said] │
│                         │                                │
└─────────────────────────┴────────────────────────────────┘
```

**Design notes:**

- **Progress dots** (● ● ○ ○) top-left — simple, low-text way to show where they are in the 4 concepts. Active dot is filled, upcoming are empty.
- **Two-column split:** Sim view left (~55% width), agent dialogue right (~45%)
- The sim view should **highlight the active joint** — colored overlay or pulsing glow on the joint being discussed, everything else slightly dimmed
- Agent dialogue panel has a speech bubble shape to reinforce the conversational feel
- **Mic button** is the primary interactive element on the right side — large, circular, with a pulsing animation when listening. Shows a brief transcript of what it heard immediately below.
- Skip button top-right is small and low-contrast — always present but not the focus
- Concept title at top left anchors the child ("I know what I'm learning right now")

---

### Screen 3 — Sim Playground (Adaptive Phase)

**Purpose:** Free exploration in sim after completing the 4 concepts.

**Layout:**

```
┌──────────────────────────────────────────────────────────┐
│  Free Practice                             [I'm ready →] │
├─────────────────────────┬────────────────────────────────┤
│                         │  [AI Reasoning Stepper]        │
│   [MuJoCo sim view]     │  ┌──────────────────────────┐  │
│   (full robot, no       │  │ 1 ✓ You said...          │  │
│    highlights)          │  │ 2 ▶ Understanding...     │  │ 
│                         │  │ 3 ○ Safety Check         │  │
│                         │  │ 4 ○ Clarification        │  │
│                         │  │ 5 ○ Execute              │  │
│                         │  └──────────────────────────┘  │
│                         │                                │
│                         │  [Mic button]                  │
│                         │  [Last agent message]          │
└─────────────────────────┴────────────────────────────────┘
```

**Design notes:**

- "Free Practice" label replaces the concept progress dots — signals the shift to open mode
- **AI Reasoning Stepper** appears here for the first time — this is where kids learn to read it before they see it with the real robot
- The stepper is a vertical list of numbered steps on the right panel. Only the **active step** is expanded with detail; completed steps shrink to a one-line summary + checkmark; upcoming steps are greyed out with just their label
- "I'm ready →" button top-right becomes the main CTA once at least one successful command has completed

---

### AI Reasoning Stepper — Component Detail

This component is the core AI literacy element. It appears in Screen 3 (sim playground) and Screen 5 (real robot interaction).

**States per step:**

| State | Visual |
|---|---|
| Upcoming | Grey label, no icon, collapsed |
| Active | Blue/accent color, animated spinner or pulse, expanded with detail |
| Success | Green checkmark, collapsed to one-line summary |
| Skipped | Grey label + "—" dash, collapsed (e.g., no clarification needed) |
| Blocked | Red X, expanded with reason + "Try again" button |

**Expanded step examples:**

```
▶  Understanding
   I think you want to raise CORAL's LEFT ARM.
   Does that sound right?
        [ Yes ]   [ No, let me try again ]
```

```
✓  Safety Check
   All clear! No collisions detected.
```

```
✗  Safety Check
   CORAL's arm would bump into its side at that angle.
   Try a smaller movement.
        [ Try again ]
```

**Animation guidance:**

- Steps should transition with a smooth expand/collapse (~200ms ease), not snap
- The active step's spinner should be subtle — a soft rotating arc, not a harsh loading spinner
- When a step goes from active → success, the checkmark should "pop" in (scale 0→1, ~150ms) to give satisfying feedback
- The blocked state should have a gentle shake on the step to signal error without alarming the child

---

### Screen 4 — Readiness Gate

**Purpose:** Celebrate completion of tutorial, build confidence before real robot.

**Layout:**

```
┌─────────────────────────────────────────────┐
│                                             │
│   ★  You did it!  ★                        │
│                                             │
│   [CORAL robot — celebratory pose in sim]   │
│                                             │
│   "You taught CORAL really well in there.  │
│    Ready to try with the real robot?"       │
│                                             │
│         [ Meet the real CORAL! ]           │
│                                             │
└─────────────────────────────────────────────┘
```

**Design notes:**

- Full-screen celebration moment — remove all chrome, this should feel like an achievement
- MuJoCo can display a preset "happy" or wave pose here to make the robot feel alive
- Single large CTA — no skip, no back, no distraction
- Brief confetti or particle animation is appropriate here (one of the few places to use it)

---

### Screen 5 — Main Interaction (Real Robot)

Shares the same two-column layout as Screen 3, but the sim view is replaced by the real robot camera feed.

**Layout:**

```
┌──────────────────────────────────────────────────────────┐
│  CORAL is ready                                          │
├─────────────────────────┬────────────────────────────────┤
│                         │  [AI Reasoning Stepper]        │
│   [Live camera feed     │  (same component as sim)       │
│    of real robot]       │                                │
│                         │  [Mic button]                  │
│                         │  [Agent message]               │
│                         │                                │
│   [Pose cards row]      │                                │
└─────────────────────────┴────────────────────────────────┘
```

**Design notes:**

- The AI Reasoning Stepper carries over **unchanged** — by now the child has seen it in sim and knows how to read it. This is intentional continuity.
- Pose cards appear as a horizontal scroll row at the bottom of the left panel — small thumbnails of saved poses, tappable to recall

---

### Visual Language & Style

**Color system:**

| Role | Suggested color | Usage |
|---|---|---|
| Primary / brand | Coral / warm orange | CTAs, active states, CORAL identity |
| Success | Soft green `#4CAF50` | Safety pass, step complete |
| Warning | Amber `#FFC107` | Approaching safety limit |
| Blocked / error | Soft red `#EF5350` | Collision blocked, step failed |
| Neutral / upcoming | Mid-grey `#9E9E9E` | Inactive steps, secondary text |
| Background | Off-white or very light blue-grey | Reduce eye strain vs pure white |

**Typography:**

- Use a rounded, friendly typeface — something like **Nunito**, **Poppins**, or **DM Rounded** reads well for kids and doesn't feel clinical
- Minimum 16px body text; agent dialogue bubbles at 18–20px
- All-caps sparingly — concept labels only, never body copy

**Iconography:**

- Prefer outline icons with rounded corners (Heroicons Rounded or Phosphor Icons)
- Joint labels on the sim view should use simple anatomical illustrations rather than text labels alone
- Mic button should have a clear visual microphone icon, not just a circle

**Spacing & touch targets:**

- All interactive elements minimum 48×48px tap target
- Generous padding inside panels — kids will be less precise with pointing/clicking
- Avoid tight information density — when in doubt, show less

**Motion principles:**

- Transitions between concept stages: slide or fade (~300ms) — not instant cuts
- Stepper step transitions: expand/collapse (~200ms ease-in-out)
- Sim view joint highlights: pulsing glow, ~1s loop, not distracting
- Avoid bouncy/springy animations — they can feel chaotic for neurodivergent users

---

### Facilitator View (optional layer)

A secondary view the facilitator can see (second monitor, or toggled overlay) that shows:

- Which phase the child is in
- Full transcript of the session
- Raw LLM intent output alongside what the child sees
- "Mark as Ready" button to manually advance past the readiness gate
- Toggle to disable/enable tutorial auto-launch for next session

This doesn't need to be designed for v1 but is worth reserving layout space for in the component architecture.
