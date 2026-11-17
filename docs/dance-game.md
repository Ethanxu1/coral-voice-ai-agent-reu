# Dance Game: Handover

A block-coding activity for children. The student makes their own moves in the [Pose Designer](pose-designer.md), then drags those moves and "repeat" loop blocks from a shelf, snaps them under a "when ▶ Dance! is pressed" block (nesting loops inside loops if they want), then presses **Dance!** to watch the simulated CORAL perform the routine.

This document covers what exists, how it works, how to run and change it, and what is still open.

For setup and running the stack, see the [README](../README.md). For the overall system, see [overview.md](overview.md).

---

## 1. What it does

Entry point: the **Dance Game** button on the home page (`/`), route `/dance-game`. There is no menu/mode split like Rock Paper Scissors has: Dance Game is one continuous build-and-play activity.

The screen has the same look as Rock Paper Scissors Play (sand room, Fredoka type, CORAL on a pink stage floor, the shared colour palette):

| Area | Contents |
|---|---|
| Left card | A [Blockly](https://developers.google.com/blockly) workspace. A shelf down its left side holds one **repeat** block, an **＋ Add move** button, and one move block per pose the child has made (there are no preset moves). The **when ▶ Dance! is pressed** start block is already placed and can't be deleted. |
| Right | CORAL's speech bubble, the simulator robot, and the big **Dance!** / **Stop** button |
| Corner | The grown-up menu shared with RPS (connection, How to play, hold-to-exit) |

**＋ Add move** opens the [Pose Designer](pose-designer.md); once the child saves a pose there, it returns to the Dance Game with the new move on the shelf. With no moves yet, the shelf says "No moves yet!" and CORAL's bubble says to press Add move.

Students drag blocks off the shelf and snap them under the start block; a repeat block is C-shaped and takes blocks inside it, including other repeat blocks. Each move block has a speed dropdown (🐢 slow / 🚶 normal / 🐇 fast); each repeat block has an editable count (1-20). Only blocks connected under the start block play: Blockly greys out loose ones. Dragging a block back to the shelf (or onto the trash can) deletes it.

**Dance!** is disabled until there is at least one move under the start block. Pressing it locks the blocks (the workspace goes read-only and the shelf dims), resets the robot to a clean stand, walks the program in order, holds the last pose for a second, and resets to stand. While it plays, the running block glows gold and the bubble shows the current move. Moves never stop part-way because of self-collision: if the direct motion would bump a limb into the body, the server goes around it through an intermediate pose. Each move waits until the robot has physically arrived in the pose before the next one starts. **Stop** cancels after the current move.

---

## 2. How it works

```
poseDesigner/customPoses.ts (the child's saved poses, localStorage)
        |
        v
dance/poses.ts (danceMove(id) -> pulses; slow/normal/fast -> ms)
        |
        v
dance/blocks.ts (Blockly block types, theme, shelf; workspace -> Step[])
        |
dance/DanceWorkspace.tsx (Blockly.inject; reports the program on every change)
        |
        v
dance/sequencePlayer.ts (walks the steps)  --->  POST /set-pose (duration_ms glide), POST /reset
```

### Blocks (`dance/blocks.ts`)

Blockly owns dragging, snapping, nesting, deleting and the shelf. This file defines:

- `dance_start`: the hat block (navy). Only its stack plays.
- `dance_repeat`: `repeat [n] times` with a statement input `DO` (teal).
- `dance_custom`: a move, `<stick figure> [pose ▾] [speed ▾]` (coral). The shelf holds one per saved pose, preset to that pose.
- The shelf's `＋ Add move` button (`ADD_MOVE_CALLBACK`) calls `DanceWorkspace`'s `onAddMove`; the page navigates to `/pose-designer` with `state.from = '/dance-game'`, and the designer returns there after saving.

`danceTheme()` builds a Blockly theme from `src/theme/palette.css`: Blockly needs real colour values, not `var()`, so it reads the `--pal-*` custom properties at runtime with `getComputedStyle`. Renderer is `zelos` (Scratch-like rounded blocks).

`readProgram(workspace)` turns the stack under the start block into a plain `Step[]` tree:
- `{ kind: 'pose', blockId, pose, speed }`
- `{ kind: 'repeat', blockId, times, body: Step[] }`

Disabled blocks (loose, or disabled from the context menu) are skipped. `blockId` is kept so the player can highlight the block that is running.

### The workspace (`dance/DanceWorkspace.tsx`)

Injects Blockly once, places the undeletable start block, adds `Blockly.Events.disableOrphans` (greys out loose stacks) and a change listener that calls `onChange(readProgram(ws))` for every non-UI event. A `ResizeObserver` calls `Blockly.svgResize`. `locked` maps to `workspace.setIsReadOnly()`; the ref handle exposes `highlight(blockId)` (`workspace.highlightBlock`).

The page route is lazy-loaded (`App.tsx`) so Blockly (~700 KB) stays out of the bundle other pages download.

### Playback (`dance/sequencePlayer.ts`)

`playSequence()` calls `/reset`, recursively walks the steps (a repeat step re-walks its `body` `times` times), and calls `/reset` again at the end. Each move is one `setPose(pulses, { durationMs, waitUntilArrived: true })`. The server glides the motor targets there over `durationMs`; the joints trail those targets under physics (soft arm motors, sim slower than real time), so with `wait_until_arrived` the server then polls the real joint angles and replies once they are within ~3° of the pose, have stopped moving (some poses are never fully reached), or 3 s have passed (`wait_until_arrived` in `backend/app/services/motion.py`). No stand between repeat laps or sibling moves, so the routine reads as continuous. The end is a reset rather than a glide back to stand: gliding out of Warrior's deep lunge folded the sim over in testing.

Cancellation is a single incrementing token owned by the page (`DanceGame.tsx`), checked before every move.

---

## 3. File map

### Frontend

| File | Purpose |
|---|---|
| `frontend/src/pages/DanceGame.tsx` | The page: program state, Play/Stop, the bubble, How to play |
| `frontend/src/pages/DanceGame.css` | Page styles (`.dance`), including the Blockly overrides (shelf labels, gold highlight, dimmed shelf while locked) |
| `frontend/src/dance/poses.ts` | `danceMove(id)` (a saved pose as a move), the stand pulses, speed-to-ms and speed labels |
| `frontend/src/dance/blocks.ts` | Blockly block definitions, palette theme, shelf, `readProgram` |
| `frontend/src/dance/DanceWorkspace.tsx` | React wrapper around the Blockly workspace |
| `frontend/src/dance/sequencePlayer.ts` | Walks the program and drives the simulator |
| `frontend/src/poseDesigner/customPoses.ts` | The child's own poses (from the Pose Designer), read for the shelf's moves |
| `frontend/src/rps/CornerMenu.tsx`, `CornerMenu.css` | Grown-up corner menu shared with RPS (`menuPath={null}` hides "Game menu") |
| `frontend/src/App.tsx` | Home-page button and the lazy `/dance-game` route |

### Backend

Moves are the child's saved pulse dicts; `/set-pose` accepts any joint-pulse dict. The backend additions are `/set-pose`'s collision detours for glides (`CollisionChecker.plan_path`, `services/motion.planned_safe_path`; used by every `/set-pose` glide) and its opt-in `wait_until_arrived` (`schemas/requests.py`, `services/motion.py`, `AiNexSimulator.get_actual_joint_positions`), used only by this game.

---

## 4. Running it

```bash
./run.sh
```

Open <http://localhost:5173> and click **Dance Game**. Simulation mode is enough; no robot is needed.

---

## 5. Changing things

| I want to... | Edit |
|---|---|
| Add a move | Press **＋ Add move** and make it in the Pose Designer (there are no preset moves since 2026-11-12) |
| Change how fast slow/normal/fast are | `SPEED_MS` in `dance/poses.ts` |
| Change block colours | The `--pal-*` values in `src/theme/palette.css`, or which ones `danceTheme()` in `dance/blocks.ts` uses |
| Change the max repeat count | `MAX_REPEAT` in `dance/blocks.ts` |

---

## 6. Known issues and open items

1. **Sim-only.** Moves don't use `to_robot`, so the physical robot never dances. These are full-body poses with leg moves (Warrior lunges, Dab bends the knees), so sending them to hardware needs a deliberate check against the Pi's `SERVO_LIMITS` and fall behaviour first.
2. **Fall-blocked moves are skipped silently.** `/set-pose` runs the collision/fall gate; a move it blocks just doesn't happen, with no message to the child.
3. **The program isn't saved.** Leaving or refreshing the page clears the blocks.
4. **Many moves are fall-blocked.** The fall check refuses e.g. most moves into Warrior and most moves out of Thinker or Dab, and a refused move is skipped. Its prediction starts the robot in the previous pose at normal standing height, which is wrong for bent-knee poses, so these refusals are probably over-cautious. Pre-existing; not changed yet.
5. **Preset moves removed (2026-11-12).** The shelf holds only the child's own Pose Designer moves; the old presets remain as data in `backend/app/robot/motions.py`.
6. **Moves are per browser.** Saved poses live in localStorage, so another browser starts with an empty shelf.
7. **Block icons are emoji, not stick figures.** There's no code yet that derives full-body limb geometry from a pulse dict.
8. **No automated tests.** The frontend has no test runner. `readProgram` is the piece worth unit-testing if one is added.
9. **No music yet.** Custom moves come from the [Pose Designer](pose-designer.md): `dance_custom` blocks (`blocks.ts`), resolved by `danceMove()` (`poses.ts`). The shelf is built when the page opens, so a pose saved in another tab shows up after a reload.
