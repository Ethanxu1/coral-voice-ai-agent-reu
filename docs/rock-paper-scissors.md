# Rock Paper Scissors: Handover

A gesture game for children. The child learns three arm poses (rock, paper, scissors), then plays against CORAL. The camera reads the child's pose, and the simulated robot plays its own move.

This document covers what exists, how it works, how to run and change it, and what is still open.

For setup and running the stack, see the [README](../README.md). For the overall system, see [overview.md](overview.md).

---

## 1. What it does

Entry point: the **Rock Paper Scissors** button on the home page (`/`).

| Route | Screen | What happens |
|---|---|---|
| `/rock-paper-scissors` | Menu | Two cards: Learn gestures, Let's play |
| `/rock-paper-scissors/learn` | Learn | Pick a move, see how to do it, and see what the system thinks you are doing |
| `/rock-paper-scissors/play` | Play | 3-2-1 countdown, the child strikes a pose, CORAL plays a random move, the round is judged and scored |

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

### The game round (`playRound` in `RockPaperScissors.tsx`)

1. Reset the robot to stand.
2. Countdown 3, 2, 1 (reuses the Refined Demo countdown modal).
3. "Shoot!": the robot eases into a random gesture while the camera is sampled every 50 ms for 1.3 s.
4. The child's move is the gesture seen most often in that window. If none was seen, CORAL asks the child to step back and try again.
5. Judge, update the score, announce the result in chat and by voice.

---

## 3. File map

### Frontend

| File | Purpose |
|---|---|
| `frontend/src/pages/RockPaperScissorsMenu.tsx` | Menu screen |
| `frontend/src/pages/RockPaperScissors.tsx` | The Learn and Play screens (one component, `mode` prop) |
| `frontend/src/pages/RockPaperScissors.css` | Styles only for what the Refined Demo does not already have |
| `frontend/src/pose/poseSimilarity.ts` | **Generic, reusable** pose matching. No game code |
| `frontend/src/rps/gestures.ts` | **The one place to define the gestures**: labels, teaching text, stick figure, robot pose, detection settings |
| `frontend/src/rps/classify.ts` | Thin wrapper: `classifyGesture()` and `gestureScores()` using the generic matcher |
| `frontend/src/rps/robotPose.ts` | Eases the simulator robot's arms to a pose in small steps |
| `frontend/src/rps/GestureFigure.tsx` | Draws a gesture's stick figure |
| `frontend/src/rps/StandardPicture.tsx` | View 1: image from `public/rps/` or the stick figure |
| `frontend/src/rps/SkeletonView.tsx` | View 4: the tracker's stick figure and the readiness message |
| `frontend/src/App.tsx`, `App.css` | Home-page button and routes |
| `frontend/src/demo/api.ts` | Added `setHiplessFollow()` |
| `frontend/src/pages/RefinedDemo.tsx` | Only change: `ChatArea` and `ConnectionHealthDot` are now exported for reuse |

### Backend

| File | Change |
|---|---|
| `backend/app/vision/pose_to_robot.py` | Optional hip-less mode: if the hips are not visible, the torso frame is built from the shoulders alone, assuming an upright torso |
| `backend/app/follow_controller.py` | Optional gentle mode: slower commands, harder filtering, and a per-tick limit on how far any joint may move |
| `backend/app/api/routes/state.py` | `POST /follow/hipless-arms` switches both modes on or off |

Both backend modes are **off by default**, so the main demo behaves exactly as before. The Learn screen turns them on when it opens and off when it closes.

---

## 4. Running it

```bash
./run.sh -speaker
```

Open <http://localhost:5173> and click **Rock Paper Scissors**.

- Simulation mode is enough. No robot is needed.
- The speaker server is only needed for CORAL's voice.
- Restart the backend after pulling these changes. The new endpoint does not exist in an already-running server, and the follow behaviour will not change until it restarts.
- Stand so that your head, shoulders and both arms are in view. Hips are not needed.

---

## 5. Changing things

| I want to... | Edit |
|---|---|
| Change what a gesture looks like to the child | `figure` in `rps/gestures.ts`. This changes the picture and the detection reference together |
| Change what the robot does for a gesture | `robotPulses` in `rps/gestures.ts` (hardware servo pulses, same format as `robot/motions.py`) |
| Make detection stricter or looser | `DETECTION` in `rps/gestures.ts`: `minSimilarity` (lower is looser), `maxDistance` (higher is looser), `margin` |
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
2. **Detection thresholds are estimates.** They were checked with synthetic data only (ideal poses plus noise, and everyday poses such as arms down and hands on hips). With realistic landmark jitter the three gestures were recognised 96 to 100% of the time in that test. They have not been validated with real children. Expect to tune `minSimilarity`.
3. **Arms pointing at the camera look like rock** in a 2D image (similarity about 0.70). `minSimilarity` is set to 0.72 to keep this out, which makes detection fairly strict.
4. **Gentle follow mode has not been tuned on a live run.** It was written to stop the simulated robot toppling on fast arm swings. Check it by moving quickly and adjust `_GENTLE_*`.
5. **Hip-less mode assumes an upright torso.** If the child leans a lot, the arm angles will be off.
6. **The follow settings are global state in the main server process**, switched by `POST /follow/hipless-arms`. Two Learn screens open at once, or a crash that skips the cleanup request, can leave them on. Restarting the backend resets them.
7. **Robot motion in the game is simulator-only.** Poses are sent with `POST /set-pose`, which snaps joints and bypasses the collision and fall checks. `robotPose.ts` eases in small steps to avoid toppling. Running this on the physical robot would need a safer path, such as the `/move` route.
8. **The 3D viewer sometimes stays blank in an embedded preview** until the window is resized. This was seen only in the Claude preview pane, not in Chrome.
9. **No automated tests.** The frontend has no test runner. The matcher is a pure function and is easy to unit-test if one is added.
10. **Voice lines go to the speaker server and are best effort.** If it is not running, the game works silently.

### Ideas for next steps

- A "save my current pose as Rock" button that records a template from the live camera. The matcher already treats templates as plain data, so this needs only a UI and storage.
- A body-pose-based classifier or a trained model if the rule-free similarity match proves too crude.
- Real photos for view 1.
