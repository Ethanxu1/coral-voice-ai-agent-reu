# Dance Game: Handover

A block-coding activity for children. The student drags preset robot poses and "Repeat" loop blocks onto a canvas, nesting loops inside loops if they want, then presses Play to watch the simulated CORAL perform the routine.

This document covers what exists, how it works, how to run and change it, and what is still open.

For setup and running the stack, see the [README](../README.md). For the overall system, see [overview.md](overview.md).

---

## 1. What it does

Entry point: the **Dance Game** button on the home page (`/`), route `/dance-game`. There is no menu/mode split like Rock Paper Scissors has — Dance Game is one continuous build-and-play activity.

The screen is three panels:

| Panel | Contents |
|---|---|
| Left | The block palette: one **Repeat** control block, and nine preset pose blocks (Stand, T-Pose, Dab, Superhero, Thinker, Muscles, Hand Raised, Warrior, Wave) |
| Middle | The simulator robot |
| Right | The canvas where the student assembles their routine, plus Play/Stop |

Clicking a palette card appends that block to the end of the top-level sequence. From there, the student **drags blocks to reorder them**, and can **drag a block inside a Repeat block's body** to nest it — Repeat blocks can themselves be dragged inside other Repeat blocks, so loops can nest arbitrarily deep, the same way Scratch's C-shaped `repeat` block works. Each pose block has its own Slow / Normal / Fast speed tag (click to cycle). Each Repeat block has its own editable repeat count. There is no single global "repeat everything" control — repetition only happens through Repeat blocks the student places.

Pressing **Play** resets the robot to a clean stand, walks the top-level sequence in order (a Repeat block loops its contents that many times before continuing), and settles back to stand at the end. **Stop** cancels after the current move finishes easing.

---

## 2. How it works

```
backend/app/robot/motions.py (pulse dicts, ported by hand)
        |
        v
dance/poses.ts (9 preset poses + Slow/Normal/Fast -> ms)
        |
        v
PoseLibrary.tsx (click -> append block)  --->  dance/blocks.ts (the block tree)
                                                        |
                                            SequenceBuilder.tsx (drag to reorder/nest)
                                                        |
                                                        v
                                          sequencePlayer.ts (walks the tree)
                                                        |
                                                        v
                                        pose/robotPose.ts  --->  POST /set-pose
```

### The block tree (`dance/blocks.ts`)

A sequence is `Block[]`, where a `Block` is either:
- a **pose block** (`{ type: 'pose', uid, poseId, speed }`) — a leaf, one move
- a **repeat block** (`{ type: 'repeat', uid, count, children: Block[] }`) — a loop wrapping a nested `Block[]`, which may itself contain repeat blocks

Every block carries a `uid` (`crypto.randomUUID()`), separate from `poseId`, so the same preset can be added to the sequence more than once.

Reordering and nesting both go through one function, `moveBlock(tree, sourceUid, destParentUid, beforeUid)`. It locates both the source and the destination **by uid**, not by numeric index, specifically so it never has to reason about index arithmetic shifting after a removal. It also refuses (silently no-ops) any move that would place a block inside its own subtree, which would otherwise create a cycle — e.g. dragging a Repeat block into one of its own nested children.

`frontend/src/dance/blocks.ts`'s tree functions (`moveBlock`, `removeBlock`, `mapBlock`) are pure and framework-free; they were exercised directly with `npx tsx` against hand-built scenarios (nest, reorder, cycle-guard, remove, update) during development, independent of the UI.

### The canvas UI (`dance/SequenceBuilder.tsx`)

Built with native HTML5 drag-and-drop (`draggable`, `onDragStart`/`onDragOver`/`onDrop`) — the same mechanism already used for the end-session dance replay in `RefinedDemo.tsx`, generalized here to nested drop targets. No drag-and-drop library is installed in this project.

`BlockList` renders one level of the tree and is called recursively for a Repeat block's body. Every block row is simultaneously a drag source (grab it to move it) and a drop target (drop something on it to insert that thing just before it); every list also has a trailing drop zone to append at the end. Every drag/drop handler calls `stopPropagation()`, which is what keeps a drop on a nested, inner list from also firing the outer list's handler.

### Playback (`dance/sequencePlayer.ts`)

`playSequence()` resets to stand, recursively walks the block tree (a repeat block's `count` just re-walks its `children` that many times), and resets to stand again at the end. No reset-to-stand between repeat laps or between sibling blocks — one move eases straight into the next so the routine reads as continuous. Cancellation is a single incrementing token owned by the page (`DanceGame.tsx`), checked before and after every move, same pattern as `RockPaperScissors.tsx`'s `runIdRef` and the existing (unrelated) end-session dance loop's `danceTokenRef`.

### Driving the simulator (`pose/robotPose.ts`)

A sibling of `rps/robotPose.ts`'s easing logic, kept as a **separate file** rather than shared, specifically so this feature doesn't touch anything under `rps/`. `poseRobot(target, durationMs)` eases the sim robot's pose in 10 interpolated `/set-pose` calls (avoids toppling the physics model from an instant snap). The one real difference from the RPS version: `resetToStand(standPulses)` seeds the module's local "where is the robot right now" tracking with a **full-body** stand pose, not RPS's 8-arm-joint rest pose — otherwise the very first dance move's leg joints would snap instead of ease, since they'd have no prior tracked value.

---

## 3. File map

### Frontend

| File | Purpose |
|---|---|
| `frontend/src/pages/DanceGame.tsx` | The page: owns the block tree state, mount/unmount cleanup, Play/Stop |
| `frontend/src/pages/DanceGame.css` | Styles only for what the Refined Demo shell does not already have |
| `frontend/src/dance/blocks.ts` | The block tree data model and its pure tree operations (`moveBlock`, `removeBlock`, `mapBlock`) |
| `frontend/src/dance/poses.ts` | **The one place to define the preset poses**: labels, emoji, robot pulses, speed-to-ms mapping |
| `frontend/src/dance/sequencePlayer.ts` | Walks the block tree and drives the simulator |
| `frontend/src/dance/PoseLibrary.tsx` | Left panel: the block palette |
| `frontend/src/dance/SequenceBuilder.tsx` | Right panel: the recursive drag-and-drop canvas |
| `frontend/src/pose/robotPose.ts` | **Generic, reusable** pose easing — no game code. Sibling of `rps/robotPose.ts`, see note above on why it isn't shared |
| `frontend/src/App.tsx`, `App.css` | Home-page button and the `/dance-game` route |

### Backend

None. `/set-pose` already accepts any joint-pulse dict, so the preset poses were ported into `dance/poses.ts` as data rather than fetched live. `backend/app/robot/motions.py` is read-only reference material for that port, not something this feature changed.

---

## 4. Running it

```bash
./run.sh
```

Open <http://localhost:5173> and click **Dance Game**.

- Simulation mode is enough. No robot is needed.

---

## 5. Changing things

| I want to... | Edit |
|---|---|
| Add another preset pose | Add an entry to `DANCE_POSES` in `dance/poses.ts` (pulse dict + emoji + label) and extend `DancePoseId` |
| Change how fast Slow/Normal/Fast are | `SPEED_MS` in `dance/poses.ts` |
| Change the reset/baseline pose | `STAND_PULSES` in `dance/poses.ts` |
| Change the max repeat count or sequence depth guard | `min`/`max` on the number input in `SequenceBuilder.tsx`'s `RepeatBlockRow` |

---

## 6. Known issues and open items

1. **Sim-only; `/set-pose` bypasses collision and fall checks.** Same documented caveat as Rock Paper Scissors. `pose/robotPose.ts` eases in small steps specifically to avoid toppling, but running this on the physical robot would need a safer path.
2. **`wave` is one static frame, not the full animation.** `motions.py`'s `WAVE` is a 9-frame sequence; its *last* frame is identical to the resting stand-arms pose (it's the wind-down), so using it would make the "Wave" card look just like "Stand". Frame 0 (arms raised) is used instead as a single representative pose. Playing the full multi-frame animation when a Wave block's turn comes up is a natural next step, not built here.
3. **Thumbnails are emoji, not full-body stick figures.** `rps/GestureFigure.tsx`'s stick-figure renderer draws from 4 hand-authored arm points; there's no existing code that derives limb geometry (hips, knees, ankles) from a pulse dict. Building that is a reasonable fast-follow.
4. **`pose/robotPose.ts` duplicates `rps/robotPose.ts`'s easing loop.** Kept separate only because this feature was built without touching any `rps/` file. A future cleanup could unify both into one shared module that both games import, each with their own reset pose.
5. **No automated tests for the UI.** The block-tree logic in `dance/blocks.ts` (nesting, reordering, the cycle guard, remove, update) is pure and framework-free and was exercised with a throwaway `npx tsx` script against hand-built scenarios during development — worth turning into a real test file if a test runner is ever added to this project (none exists today, see the Rock Paper Scissors handover doc).
6. **No custom-pose capture yet.** Explicitly out of scope for this iteration — presets only. The natural next step, and the block-tree/player architecture doesn't need to change to support it: a new pose just needs to land in `DANCE_POSES`.

### Ideas for next steps

- Custom pose capture: a "save my current pose" button, recording from the live camera or from manual joint sliders, added as a new entry in `DANCE_POSES` (or a parallel student-authored list merged into the palette).
- Play the full multi-frame `wave` animation when its block's turn comes up, instead of flattening it to one frame.
- Full-body stick-figure thumbnails instead of emoji.
- A drop-shadow or "invalid drop" cursor while dragging a Repeat block over its own descendants, so the existing cycle guard's no-op is visible feedback rather than a silent no-op.
