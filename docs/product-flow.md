*Below are listed each of the "stages" of the demo, corrected against the current codebase (`Welcome.tsx` → `Tutorial.tsx` → `RefinedDemo.tsx`). `ProDemo.tsx` is a separate internal testing flow — see the appendix.*

---

**1. INTRO**

Hi there! My name is Coral, and I am a robot who loves to learn new poses. If you would like, we can do a tutorial together showing what I can and can't do!

UI: two buttons only — **"Let's do the tutorial"** and **"Skip to the lesson"**.
*(No sim-vs-physical "perform wave motion" buttons on this screen, and no livestream panel here — that's on the demo screen itself, not the intro.)*

---

**2. TUTORIAL**

1. Welcome
2. Explore movements *(block picker: pick a body part + a direction, then execute — this doubles as the sandbox step, see Phase 4)*
3. Joints & Movement — real voice-to-text demo
4. Instructions & Intent — ~~a live classifier~~ **scripted**: always shows the same "I think you want the LEFT ARM" example; Yes/No both just advance
5. Safety (keep as is)
6. ~~Save (i think we can get rid of this step, it feels obvious after the other ones)~~ **keep this step** — it's a full countdown → capture → analyze → name → save replay, not a trivial click
7. Ready

Phase 1 (Entry): Intro to the agent and what the user will do

Phase 2 (Sim intro): Introduce the child to the simulator via the Explore block picker — what joints it can move

Phase 3 (Guided Concepts): Joints/Movement, Intent, Safety, Save concept screens — voice commands and how they work

Phase 4 (Adaptive Phase) — optional:
- No dedicated screen exists for this. Explore already lets the child freely try part + direction combos *before* the guided concepts, so it doubles as the sandbox phase rather than being a separate step at the end.

---

**3. OPENING**

There's no separate scripted "instructions" screen before the loop starts. When the live demo loads, Coral opens with:

*"Hi! I can follow your movements and help you capture poses. Just tell me what to do!"*
— with quick-reply chips: Follow my movement / Capture my pose / My Poses.

There is no "cross your arms" gesture and no suggested-pose list — the child triggers a capture by *saying* something like "capture my pose."

---

**4. POSE MATCHING LOOP**

The live demo is a continuous voice loop, not just this one sequence — every utterance is classified into an intent (`follow_start` / `follow_stop` / `capture` / `library` / `exit` / `chat`). Only the `capture` branch below matches the original pose-matching flow.

*POSE*
- Countdown (3‑2‑1), robot locked so it doesn't jitter mid-hold
- Camera "takes picture" (captures the current livestream frame)
- Frame is sent to the vision server's `/map-features` — MediaPipe produces landmarks
- Landmarks -> ~~gesture~~ **servo joint angles, directly** — there's no separate "gesture" abstraction in between
- Execute robot move (sim, and physical robot concurrently in robot mode)

*RECORD*

"Awesome pose! Want to fine-tune it, or save it as is?"
- Recorded audio is passed to Whisper (local) -> text
- Text goes straight to the motion-planner LLM — no separate intent-classifier step here (that classifier only runs once per turn, at the top level, to route follow/capture/library/exit/chat)
- **Repeat until satisfied**: the LLM returns a `satisfied` flag each turn; the loop repeats until it's `true`
- Corrections: ~~allow for the robot to ask clarifying questions~~ there's no dedicated clarifying-question turn type — the planner's own reply text fills that role when it doesn't understand
- Continue until user is satisfied
- Motion planner: ~~map words to a gesture~~ **single LLM call**, returns JSON waypoints
  - ~~Regex~~ regex is only a fast-path for a handful of fixed system phrases ("follow me," "save this"), not general motion
- The robot executes in ~~simulation to ensure "safe" motion~~ **sim and physical robot together** — a `CollisionChecker` shadow-rolls the trajectory first and clamps any joint that would self-collide, rather than a separate sim-only approval pass
- ~~Repeat the above steps until the user is satisfied with the simulated movement~~ (same `satisfied` loop as above — sim and hardware aren't staged separately)
- ~~THEN, physical robot actually executes the movement~~ sim + hardware move at the same time, not sequentially
- ~~Robot holds pose for some time, then executes stand pose~~ not implemented — the robot stays in the captured pose until the next command

*NAME*

"What should we call it?"
- Name captured by voice (Whisper transcript)
- ~~Name, selected frame, landmarks and pose servo cmds stored in a db~~ **only the name + joint angles are stored** — not the frame or landmarks. The table is cleared on every server restart, so poses don't persist across sessions.

---

**5. OUTRO**

"You might be wondering how I knew which move to do. I have a special machine that tells me where your arms and legs are in the picture, and then I use that to make my arms and legs match that pose!"

This copy lives today inside the **End Session** exit-confirm overlay in the live demo, not a separate outro screen. A standalone `Outro.tsx` page exists at `/outro` with the same text, but nothing currently navigates to it — worth deciding whether to wire it back in or remove it.

---

**Appendix: `ProDemo.tsx`**

This is the flow that most literally matches "arms-crossed → countdown → capture → adjust → name," repeated a fixed number of times. It's explicitly an internal testing tool (no speaker, no intro/outro, no coaching pages), reachable only at `/prodemo` — don't conflate it with the kid-facing demo above when writing about the product flow.
