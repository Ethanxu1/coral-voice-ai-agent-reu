# Rock Paper Scissors: Handover

A gesture game for children. The child learns three arm poses (rock, paper, scissors), then plays against CORAL. The camera reads the child's pose, and the simulated robot plays its own move.

This document covers what exists, how it works, how to run and change it, and what is still open.

For setup and running the stack, see the [README](../README.md). For the overall system, see [overview.md](overview.md).

---

## 1. What it does

Entry point: the **Rock Paper Scissors** button on the home page (`/`).

| Route | Screen | What happens |
|---|---|---|
| `/rock-paper-scissors` | Menu | Three cards: Learn gestures, Let's play, Make your own moves |
| `/rock-paper-scissors/learn` | Learn | Pick a move, see how to do it, and see what the system thinks you are doing |
| `/rock-paper-scissors/play` | Play | A three-round match laid out as in Sayali's wireframes (see below) |
| `/rock-paper-scissors/custom` | Make your own moves | The child records their own rock, paper and scissors |
| `/rock-paper-scissors/play?moves=custom` | Play | The same match with the child's own moves |

### Play

1. **Ready?** starts the match. The child pressed it at the computer, so the game first waits until both arms are in view for a second ("Step back so I can see both of your arms").
2. Each round: the words ROCK, PAPER, SCISSORS light up one per second, then SHOOT! CORAL strikes a random move while the camera is sampled for 1.3 s.
3. The header shows ROUND n/3, the score, a verdict banner and a cheat sheet of the three moves. Below are three panels: CORAL, the camera, and the tracker's stick figure with the similarity score.
4. A round where no move was seen is replayed. Draws count as a round. After three rounds a summary shows the score and the winner, with Rematch.

Each round's result keeps the best similarity score and the time from SHOOT! until the move was first seen (`reactionMs`). Nothing is stored yet: how game data is recorded is waiting on the PIs.

### Make your own moves

The robot follows the child while they pose (same gentle follow as Learn). **Record** stays disabled until following has started. For each move the child presses **Record**, gets 3 s to step back, makes the move and holds still. The move is saved, and the next one starts by itself, when both:

- the child has held still for 1.5 s (no joint moves more than 0.15 shoulder widths), and
- the robot has caught up: over the last 0.8 s no arm joint ranged more than 60 pulses (`rps/useRobotSettle.ts`). Gentle follow lags the child, and a held pose still wobbles 20-50 pulses from landmark noise, while catching up moves about 380 pulses a second, so 60 separates the two.

If the robot never settles, the move is saved after 5 s of holding anyway. While waiting the screen says "CORAL is still catching up". **Save now** lets a partner save by hand; **Cancel** stops recording.

Each move is saved twice: the child's normalized pose (the reference for detection) and the robot's arm pose averaged over that last 0.8 s, read from `GET /joint_states/pulses` (what CORAL does when it plays that move). A pose that looks like arms hanging down is rejected, and so is a robot pose still at the stand (CORAL didn't copy it). If two moves are too alike (similarity 0.6 or more) the child is asked to redo one, and Play stays disabled until they are distinct.

Custom moves are kept in memory for the browser session only; a page refresh clears them (and so does nothing else, so after a code hot-reload old moves can linger: refresh). They are matched without the mirrored-camera check, so "left arm up" and "right arm up" count as different moves.

### How CORAL moves in the game

`poseRobot()` in `rps/robotPose.ts` sends one `POST /set-pose` with `duration_ms`, so the simulator interpolates the arms there smoothly, the same servo path follow mode uses. The duration comes from the gentle-follow speed (0.08 rad per 50 ms, about 380 pulses a second), with a 0.4 s minimum: a full arm swing takes about 1.7 s. An instant `/set-pose` snap (no `duration_ms`) can topple the simulated robot. The verdict is shown only once CORAL has finished its move.

### Gesture Studio (`/gestures`)

A separate tool on the home page, built alongside this game, for recording any gesture into a library (localStorage, exportable as JSON) and fine-tuning how CORAL performs it. Its recorder (`pages/GestureRecord.tsx`) uses the same rule as custom moves: hold the pose (`gestures/useHoldStill.ts`, similarity based with a short glitch allowance) and wait for the robot to catch up (`useRobotSettle`).

### Learn: four views

| # | View | Source |
|---|---|---|
| 1 | Standard move | A still picture: the stick-figure drawing for the chosen gesture (or `frontend/public/rps/<id>.png` if present) |
| 2 | Robot following you | The simulator robot, driven by the existing "follow my movement" pipeline |
| 3 | What the camera sees | The vision server's annotated video feed |
| 4 | What I think your pose is | A stick figure drawn from the pose tracker's landmarks, plus per-gesture similarity scores and a message about what is missing |

View 4 exists to answer one question: when the robot does not follow, what does the tracker actually see? Joints it cannot see well are drawn faded.

### Gestures

Gestures are arm poses, not hand shapes, because the AiNex robot has no fingers.

| Gesture | Child's pose |
|---|---|
| Rock | Arms crossed over the chest |
| Paper | Arms stretched out to the sides (a T) |
| Scissors | Both arms raised in a V |

Only the head, shoulders and arms need to be in the camera frame. Hips are not required.

---

## 2. How it works

```
camera -> vision server (:8001, MediaPipe) -> body landmarks over ws://localhost:8001/ws/pose
                                                    |
                         +--------------------------+---------------------------+
                         v                          v                           v
              pose/poseSimilarity.ts        rps/SkeletonView.tsx       main server (:8000)
              "which gesture is this?"      view 4, display only       follow pipeline -> view 2
```

The landmarks are not stored anywhere. They are computed per frame and pushed to whoever is connected.

### Deciding which gesture the child is making

This is a similarity match against reference poses, in a generic module that does not know about this game.

1. `normalizePose()` turns landmarks into a description that ignores size and position: joint positions measured from the middle of the shoulders, in shoulder widths.
2. `poseSimilarity()` averages the distance between matching joints and maps it to a score from 0 to 1.
3. `matchPose()` scores the live pose against every template. It returns a best match only if the score is high enough and clearly ahead of the runner-up. Otherwise it returns null ("not recognised").

By default only the elbows and wrists are compared, so hips, legs and face never need to be visible.

Each gesture's reference pose is derived from its stick-figure drawing in `gestures.ts`, so the picture shown to the child and the pose used for detection cannot drift apart.

### The game round (`playRound` in `RpsPlay.tsx`)

1. Reset the robot to stand.
2. ROCK, PAPER, SCISSORS light up one per second.
3. "Shoot!": the robot eases into a random gesture (see "How CORAL moves in the game") while the camera is sampled every 50 ms for 1.3 s.
4. The child's move is the gesture seen most often in that window. In the game every frame counts as whichever gesture it is most similar to, with no minimum score or margin (it's a game, not a test); `DETECTION.minSimilarity` and `margin` only apply in Learn. A round is replayed only if the arms were never in view.
5. Judge, update the score, show the verdict and announce it by voice.

---

## 3. File map

### Frontend

| File | Purpose |
|---|---|
| `frontend/src/pages/RockPaperScissorsMenu.tsx` | Menu screen |
| `frontend/src/pages/RockPaperScissors.tsx` | The Learn screen |
| `frontend/src/pages/RpsPlay.tsx` | The Play screen: three-round match |
| `frontend/src/pages/RpsCustom.tsx` | Make your own moves: hands-free recording |
| `frontend/src/rps/gestureSet.ts` | A playable set of three moves: the standard set, or one built from custom moves |
| `frontend/src/rps/customMoves.ts` | The recorded custom moves (session memory) and the too-alike check |
| `frontend/src/rps/useRobotFollow.ts` | Hook: the robot follows the child while a screen is open; retries until the server is up |
| `frontend/src/rps/useRobotSettle.ts` | Hook: has the following robot caught up? Shared with Gesture Studio |
| `frontend/src/rps/RpsTopbar.tsx` | Top bar shared by the screens |
| `frontend/src/pages/RockPaperScissors.css` | Styles only for what the Refined Demo does not already have |
| `frontend/src/pose/poseSimilarity.ts` | **Generic, reusable** pose matching. No game code |
| `frontend/src/rps/gestures.ts` | **The one place to define the gestures**: labels, teaching text, stick figure, robot pose, detection settings |
| `frontend/src/rps/classify.ts` | Thin wrapper: `classifyGesture()` and `gestureScores()` using the generic matcher |
| `frontend/src/rps/robotPose.ts` | Moves the simulator robot's arms to a pose at gentle-follow speed |
| `frontend/src/rps/GestureFigure.tsx` | Draws a gesture's stick figure |
| `frontend/src/rps/StandardPicture.tsx` | View 1: image from `public/rps/` or the stick figure |
| `frontend/src/rps/SkeletonView.tsx` | View 4: the tracker's stick figure and the readiness message |
| `frontend/src/App.tsx`, `App.css` | Home-page button and routes |
| `frontend/src/demo/api.ts` | Added `setHiplessFollow()`, `getJointPulses()`, and an optional `durationMs` for `setPose()` |
| `frontend/src/pages/Gesture*.tsx`, `frontend/src/gestures/` | Gesture Studio (see above) |
| `frontend/src/pages/RefinedDemo.tsx` | Only change: `ChatArea` and `ConnectionHealthDot` are now exported for reuse |

### Backend

| File | Change |
|---|---|
| `backend/app/vision/pose_to_robot.py` | Optional hip-less mode: if the hips are not visible, the torso frame is built from the shoulders alone, assuming an upright torso |
| `backend/app/follow_controller.py` | Optional gentle mode: slower commands, harder filtering, and a per-tick limit on how far any joint may move |
| `backend/app/api/routes/state.py` | `POST /follow/hipless-arms` switches both modes on or off; `GET /joint_states/pulses` returns the robot's pose in servo pulses |
| `backend/app/api/routes/motion.py`, `schemas/requests.py` | `POST /set-pose` takes an optional `duration_ms`: ease there through the servo dispatcher instead of snapping. Without it, unchanged |
| `backend/app/follow_controller.py`, `api/routes/websocket.py`, `services/intent.py` | Follow remembers which WebSocket started it, and only that connection's disconnect stops it. Before, any connection closing (a stale tab, a hot reload) stopped a newer page's follow |

Both backend modes are **off by default**, so the main demo behaves exactly as before. The Learn screen turns them on when it opens and off when it closes.

---

## 4. Running it

```bash
./run.sh -speaker
```

Open <http://localhost:5173> and click **Rock Paper Scissors**.

- Simulation mode is enough. No robot is needed.
- The speaker server is only needed for CORAL's voice.
- Restart the backend after pulling these changes. The new endpoints and options do not exist in an already-running server, and the follow behaviour will not change until it restarts.
- After a frontend hot reload, refresh the page so custom moves and follow sessions start clean.
- Stand so that your head, shoulders and both arms are in view. Hips are not needed.

---

## 5. Changing things

| I want to... | Edit |
|---|---|
| Change what a gesture looks like to the child | `figure` in `rps/gestures.ts`. This changes the picture and the detection reference together |
| Change what the robot does for a gesture | `robotPulses` in `rps/gestures.ts` (hardware servo pulses, same format as `robot/motions.py`) |
| Make detection stricter or looser | `DETECTION` in `rps/gestures.ts`: `minSimilarity` (lower is looser), `maxDistance` (higher is looser), `margin`. The game itself ignores `minSimilarity` and `margin` (best match wins) |
| Change how fast CORAL strikes its move | `GENTLE_PULSES_PER_S` in `rps/robotPose.ts` |
| Change how long to hold when recording | `STILL_MS`, `STILL_TOLERANCE`, `MAX_HOLD_MS` in `pages/RpsCustom.tsx`; `HOLD_MS` in `gestures/useHoldStill.ts` for Gesture Studio |
| Change when the robot counts as caught up | `SETTLE_PULSES`, `SETTLE_MS` in `rps/useRobotSettle.ts` |
| Use real screenshots in view 1 | Add `rock.png`, `paper.png`, `scissors.png` to `frontend/public/rps/` |
| Change how fast the simulated robot follows | `_GENTLE_*` constants at the top of `backend/app/follow_controller.py` |
| Add another gesture | Add an entry to `GESTURES` in `rps/gestures.ts` and extend `GestureId` and `BEATS` |

### Reusing the matcher in another game

```ts
import { matchPose, type PoseTemplate } from '../pose/poseSimilarity'

const templates: PoseTemplate[] = [
  { id: 'hands-up', joints: { leftWrist: [0.8, -1.2], rightWrist: [-0.8, -1.2],
                              leftElbow: [0.7, -0.5], rightElbow: [-0.7, -0.5] } },
]

const { scores, best } = matchPose(bodyLandmarks, templates, { minSimilarity: 0.75 })
```

Coordinates are in shoulder widths from the middle of the shoulders, x to the right and y downward. Set `joints` in the options to compare other joints, and `allowMirroredGesture` to accept the left/right mirror image of a template.

---

## 6. Known issues and open items

1. **The robot's "rock" pose is approximate.** In the simulator it looks like arms bent in front of the chest, not a true cross. The simulator's camera angle makes crossed arms hard to judge. Tune `robotPulses` for rock in `gestures.ts`.
2. **Detection thresholds are estimates.** They were checked with synthetic data only (ideal poses plus noise, and everyday poses such as arms down and hands on hips). With realistic landmark jitter the three gestures were recognised 96 to 100% of the time in that test. They have not been validated with real children. Expect to tune `minSimilarity` for Learn; the game uses best match.
3. **Arms pointing at the camera look like rock** in a 2D image (similarity about 0.70). `minSimilarity` is set to 0.72 to keep this out, which makes detection fairly strict.
4. **Gentle follow mode** was checked in the simulator and the speed was judged good, with no toppling. It has **not** been tried on the physical robot, so re-check the `_GENTLE_*` values before using it there.
5. **Hip-less mode assumes an upright torso.** If the child leans a lot, the arm angles will be off.
6. **The follow settings are global state in the main server process**, switched by `POST /follow/hipless-arms`. Two Learn screens open at once, or a crash that skips the cleanup request, can leave them on. Restarting the backend resets them. There is also only one follower: the newest page to ask for it owns it.
7. **Robot motion in the game is simulator-only.** `/set-pose` with `duration_ms` dispatches `sim_only` and skips the fall check (it does run the collision check). Running this on the physical robot would need the `/move` route or similar.
8. **Each round starts with `/reset`**, which drops the robot straight into the stand pose rather than easing there. It has looked fine in the simulator.
9. **`poseRobot` calls are not cancellable.** Two overlapping calls interpolate the same joints at once until the older finishes. The game never overlaps them; Gesture Studio's fine-tuning can, briefly.
10. **The robot-caught-up limits** (60 pulses over 0.8 s) were set from one adult sitting at a desk. Check them with children standing.
11. **Nothing is stored yet**: no student ID, no per-round log, no screen recording, no pre-training quiz. Sayali asked to wait for the PIs (meeting on 2026-10-13). Each round already computes `similarity` and `reactionMs` for when logging is added.
12. **The 3D viewer sometimes stays blank in an embedded preview** until the window is resized. This was seen only in the Claude preview pane, not in Chrome.
13. **No automated tests.** The frontend has no test runner. The matcher is a pure function and is easy to unit-test if one is added.
14. **Voice lines go to the speaker server and are best effort.** If it is not running, the game works silently.

### Ideas for next steps

- A body-pose-based classifier or a trained model if the rule-free similarity match proves too crude.
- Real photos for view 1.
