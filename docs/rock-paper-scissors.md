# Rock Paper Scissors: Handover

A gesture game for children. The child learns three arm poses (rock, paper, scissors), then plays against CORAL. The camera reads the child's pose, and the simulated robot plays its own move.

This document covers what exists, how it works, how to run and change it, and what is still open.

For setup and running the stack, see the [README](../README.md). For the overall system, see [overview.md](overview.md).

## Status (2026-10-29)

- The October redesign was merged into `development` ([PR #12](https://github.com/Ethanxu1/coral-voice-ai-agent-reu/pull/12)).
- Done: Learn, a three-round Play match, Make your own moves, and Gesture Studio, all on the redesigned UI. The game was played end to end in the simulator.
- On hold until the PIs decide: the pre-training quiz, the student ID, data logging and screen recording (item 11 below).
- 2026-10-29: Play redesigned for children standing back (branch `rps-redesign-ui`); see Play below and known issue 19.
- Not checked yet: `./run.sh` on an Intel Mac or on Linux since the Apple-chip change (see "Running it"), and anything on the physical robot.

---

## 1. What it does

Entry point: the **Rock Paper Scissors** button on the home page (`/`).

| Route | Screen | What happens |
|---|---|---|
| `/rock-paper-scissors` | Menu | Three cards: Learn gestures, Let's play, Make your own moves |
| `/rock-paper-scissors/learn` | Learn | Pick a move, see how to do it, and see what the system thinks you are doing |
| `/rock-paper-scissors/play` | Play | A three-round match (see below) |
| `/rock-paper-scissors/custom` | Make your own moves | The child records their own rock, paper and scissors |
| `/rock-paper-scissors/play?moves=custom` | Play | The same match with the child's own moves |

### Play

Redesigned on 2026-10-29 for a child standing about six feet back: big things, little reading, CORAL as a character. Styles are in `pages/RpsGame.css` (scoped `.rpsg`).

- **Layout.** Left: CORAL on a warm stage, in its own coral colour (`RobotViewer look="stage"`). Right: **CORAL's eye** (`rps/CoralEye.tsx`), a coral-framed lens with a beam back toward the robot, showing a chunky stick figure of what the camera sees, with a small camera picture in its corner. Bottom: the three moves (`rps/PoseArt.tsx`), each inside a **similarity ring** that fills and turns red → yellow → green as the child's pose gets closer, reaching green at the 60% line where a move counts, with the percentage on it (`ScoreRing` in `RpsPlay.tsx`, smoothed by `useSmoothedScores`). The move CORAL sees lights up in its colour. The start screen's move pictures have the same rings. Top: the score in the display font (Fredoka) with a dot per round.
- **One message at a time**, in CORAL's speech bubble, also spoken. On-screen lines may have "!"; `say()` turns them into full stops before speaking (the voice sounded harsh with them).
- **The eye's figure.** Head, neck, shoulders, arms and torso only, drawn thick (scaled to the child's size), eased frame to frame to take out jitter. Joints the tracker isn't sure of are faint and flicker. When an elbow or hand goes past the picture's edge, that edge pulses amber (`offEdges` in `rps/bodyFit.ts`). Once a move is recognised the figure fills with the move's colour.
- **Grown-up controls** sit behind the "…" icon in the corner (`rps/CornerMenu.tsx`): connection, How to play, and Game menu / Exit, which must be held for 1.2 s. Space or Enter still presses the big button on screen.
- **Sounds** (`rps/sounds.ts`, WebAudio, no files): pop when a move is seen, ding when the child is in place, a tick per countdown word, SHOOT, a chime when the move locks in, a boop on a miss, and win, lose and tie tunes.
- **CORAL's body language** (`rps/coralMoves.ts`, arms and head only, so it can't topple): it waves on the start screen, reacts 1.5 s into each result (cheer and flex when it wins, slump with head down when the child wins, shrug on a draw), and dances (cheer, flex) at the end of the match whoever won. A small CSS hop or sag of the stage goes with the win and loss reactions.

1. **Start**: CORAL waves and says hi; three big move pictures and one big Start button. A move picture lights up if the child is already doing it.
2. **Get in place**: only the upper body is needed, so a child may sit close. `bodyFit` wants head and shoulders in view, roughly centred (shoulder midpoint within 20% of the middle), shoulders under half the frame wide; arms resting below the picture are fine. CORAL coaches by voice ("Come stand where I can see you!", "Step back!", "Scoot to the middle!", "Come a little closer!") until then, says "Perfect!" with a ding, and the eye's frame turns green. The countdown starts after at least 2 s and 1 s in place.
3. **Countdown**: one giant word at a time, each in its move's colour, with a tick: "Rock… Paper… Scissors… SHOOT!" (0.9 s each). At **Paper** (`THROW_AT`) CORAL picks at random and starts moving, so its arms arrive about when the child shoots.
4. The camera reads the child's move; their move card locks in with a chime and CORAL says "Got it!". If no move was seen: "Oops, I missed that. Again!", or "Step back a little so I can see your hands!" if a hand was past the picture's edge during the capture window, and CORAL goes back to standing and the countdown restarts.
5. **Reveal**: a big round badge for each player on their own side (CORAL's on the stage, the child's over the eye), marked with a star (won), a frown (lost) or an equals sign (draw). CORAL's bubble says the result in its voice ("You got me!", "I win this one!", "Ooh, same move!") with the reason underneath in small print for the grown-up. It stays up until someone presses **Next round** (or Space/Enter); the game never moves on by itself, so a grown-up can talk the result through first.
6. **Match over**: CORAL's line ("You beat me! Wow!", "I won! Rematch?", "Ooh, we tied! Rematch?"), the score, a round badge per round with the child's move and its mark, confetti and CORAL's dance for every outcome, and one big **Play again**.

Screenshots in `docs/images/rps/` are from the previous design (before 2026-10-29).

Each round's result keeps the best similarity score and the time from Shoot until the move was first seen (`reactionMs`). Nothing is stored yet: how game data is recorded is waiting on the PIs.

### Make your own moves

Same look as Play: CORAL copying the child on the left; on the right a card per move (figure, status, Record or Redo) and the stick figure with a hold-still ring. The robot follows the child while they pose (same gentle follow as Learn). **Record** stays disabled until following has started. For each move the child presses **Record**, gets 3 s to step back, makes the move and holds still. The move is saved, and the next one starts by itself, when both:

- the child has held still for 1.5 s (no joint moves more than 0.15 shoulder widths), and
- the robot has caught up: over the last 0.8 s no arm joint ranged more than 60 pulses (`rps/useRobotSettle.ts`). Gentle follow lags the child, and a held pose still wobbles 20-50 pulses from landmark noise, while catching up moves about 380 pulses a second, so 60 separates the two.

If the robot never settles, the move is saved after 5 s of holding anyway. While waiting the screen says "CORAL is still catching up". **Save now** lets a partner save by hand; **Cancel** stops recording.

Each move is saved twice: the child's normalized pose (the reference for detection) and the robot's arm pose averaged over that last 0.8 s, read from `GET /joint_states/pulses` (what CORAL does when it plays that move). A pose that looks like arms hanging down is rejected, and so is a robot pose still at the stand (CORAL didn't copy it). If two moves are too alike (similarity 0.6 or more) the child is asked to redo one, and Play stays disabled until they are distinct.

Custom moves are kept in memory for the browser session only; a page refresh clears them (and so does nothing else, so after a code hot-reload old moves can linger: refresh). They are matched without the mirrored-camera check, so "left arm up" and "right arm up" count as different moves.

### How CORAL moves in the game

`poseRobot()` in `rps/robotPose.ts` sends one `POST /set-pose` with `duration_ms`, so the simulator interpolates the arms there smoothly, the same servo path follow mode uses. The duration comes from the gentle-follow speed (0.08 rad per 50 ms, about 380 pulses a second) and the robot's actual current pose (read from `GET /joint_states/pulses` first), with a 0.4 s minimum: a full arm swing takes about 1.7 s. An instant `/set-pose` snap (no `duration_ms`) can topple the simulated robot. The verdict is shown only once CORAL has finished its move.

### Gesture Studio (`/gestures`)

A separate tool on the home page, built alongside this game, for recording any gesture into a library (localStorage, exportable as JSON) and fine-tuning how CORAL performs it.

The library file format (`coral-gestures`, version 1, `gestures/library.ts`) is meant to be shared, e.g. for the dance game's pose library. Only arms are recorded and tuned today, but the format already allows legs: `pose` may hold any joint `poseSimilarity` knows (hips, knees, ankles, nose) and `robotPulses` any servo in `SERVO_ID` (legs, head, grippers). The 4 arm points and 8 arm servos are required; any other known joint is kept through import, export and fine-tuning, and unknown keys are dropped. Its recorder (`pages/GestureRecord.tsx`) uses the same rule as custom moves: hold the pose (`gestures/useHoldStill.ts`, similarity based with a short glitch allowance) and wait for the robot to catch up (`useRobotSettle`).

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
2. Rock, Paper, Scissors (0.9 s each), then "Shoot" stays up 0.9 s while the child settles. At Paper (`THROW_AT`) CORAL picks a random gesture and starts easing into it (see "How CORAL moves in the game"), starting from the stand pose so it doesn't have to read the robot first. Measured: the move is sent at Paper, and Paper's arms come to rest about 0.45 s after Shoot.
3. The camera is sampled every 50 ms for 0.6 s. A frame counts as the most similar gesture if that similarity is at least 60% (`MATCH` in `RpsPlay.tsx`; Learn keeps the stricter `DETECTION.minSimilarity` of 72%). The child's move is the gesture seen most often, if it was seen in at least a third of the samples; otherwise the countdown restarts.
4. "Got it" shows for at least 1.3 s and until CORAL's arms have arrived. After a miss, CORAL is reset to stand once its move has finished, well before the next Shoot.
5. Judge, update the score, show the result and announce it by voice; 1.5 s later CORAL reacts. The next round starts only when **Next round** is pressed (`coralMoves.react`), and the next round waits for that move to finish.

CORAL speaks in the first person ("You got me!", "I win this one!"). The lines are `ROUND_LINE`, `FIT_LINE` and `finalLine` in `RpsPlay.tsx`; the same text is shown in the bubble and spoken, with "!" spoken as a full stop (with them the TTS voice sounded harsh).

CORAL's voice is the browser's own speech synthesis (Web Speech API, `audio/speech.ts`), with the Mac's Samantha voice at its normal pace (about `say -r 180`), chosen by ear. It starts within a few ms and needs no network. The first version of the game spoke the same way, through `say` on a speaker server; when that server was removed, RPS moved to OpenAI TTS through the backend's `/speak`, which took 1 to 3 s per line and sometimes stalled for 10 s or more, so lines came late or not at all. On a machine without Samantha the browser uses another local US English voice, so the voice differs on Windows or Linux.

---

## 3. File map

### Frontend

| File | Purpose |
|---|---|
| `frontend/src/pages/RockPaperScissorsMenu.tsx` | Menu screen |
| `frontend/src/pages/RockPaperScissors.tsx` | The Learn screen |
| `frontend/src/pages/RpsPlay.tsx` | The Play screen: three-round match |
| `frontend/src/pages/RpsGame.css` | The Play screen's look, scoped under `.rpsg` |
| `frontend/src/rps/CoralEye.tsx` | CORAL's eye: the chunky skeleton, green frame while getting in place, edge pulses |
| `frontend/src/rps/bodyFit.ts` | Is the child's upper body in view; which edge did an arm leave by (pure functions) |
| `frontend/src/rps/PoseArt.tsx` | The chunky move pictures, and `MOVE_COLOR` |
| `frontend/src/rps/coralMoves.ts` | CORAL's wave, round reactions and end-of-match dance |
| `frontend/src/rps/CornerMenu.tsx` | The grown-ups' corner menu with press-and-hold Exit |
| `frontend/src/rps/sounds.ts` | Play's sound effects (WebAudio) |
| `frontend/src/pages/RpsCustom.tsx` | Make your own moves: hands-free recording |
| `frontend/src/rps/gestureSet.ts` | A playable set of three moves: the standard set, or one built from custom moves |
| `frontend/src/rps/customMoves.ts` | The recorded custom moves (session memory) and the too-alike check |
| `frontend/src/rps/useRobotFollow.ts` | Hook: the robot follows the child while a screen is open; retries until the server is up |
| `frontend/src/rps/useSmoothedScores.ts` | Hook: similarity scores made readable for a child (averaged, 4 updates a second, rounded to 10%). Play uses its `matched` to light the move cards |
| `frontend/src/audio/speech.ts` | `speak()`: CORAL's lines through the browser's speech synthesis (Samantha) |
| `frontend/src/rps/useRobotSettle.ts` | Hook: has the following robot caught up? Shared with Gesture Studio |
| `frontend/src/rps/RpsTopbar.tsx` | Top bar of the Menu and Learn screens |
| `frontend/src/rps/RpsBar.tsx` | Top bar of Make your own moves: Menu and End always clickable |
| `frontend/src/pages/RpsPlay.css` | The look of Make your own moves, scoped under `.rpsp` (Play moved to `RpsGame.css`) |
| `frontend/src/pages/RockPaperScissors.css` | Styles for Menu and Learn, plus pieces Gesture Studio shares |
| `frontend/src/pose/poseSimilarity.ts` | **Generic, reusable** pose matching. No game code |
| `frontend/src/rps/gestures.ts` | **The one place to define the gestures**: labels, teaching text, stick figure, robot pose, detection settings |
| `frontend/src/rps/classify.ts` | Thin wrapper: `classifyGesture()` and `gestureScores()` using the generic matcher |
| `frontend/src/rps/robotPose.ts` | Moves the simulator robot's arms to a pose at gentle-follow speed. Pass `from` when the start pose is known, to skip reading it |
| `frontend/src/rps/GestureFigure.tsx` | Draws a gesture's stick figure |
| `frontend/src/rps/StandardPicture.tsx` | View 1: image from `public/rps/` or the stick figure |
| `frontend/src/rps/SkeletonView.tsx` | View 4: the tracker's stick figure and the readiness message |
| `frontend/src/App.tsx`, `App.css` | Home-page button and routes |
| `frontend/src/api/robot.ts` | `setHiplessFollow()`, `getJointPulses()`; `SERVO_ID` is exported for Gesture Studio |
| `frontend/src/components/ChatArea.tsx`, `ConnectionStatus.tsx` | Chat panel and health dot, shared with the Refined Demo |
| `frontend/src/pages/Gesture*.tsx`, `frontend/src/gestures/` | Gesture Studio (see above) |
| `frontend/src/components/RobotViewer.tsx` | The 3D sim viewer (shared). It normalizes streamed quaternions, see known issue 15. `look="stage"` is Play's coral-coloured, warm-lit, front-facing look; the default `lab` look is unchanged |
| `run.sh` | Starts the stack. On Apple-chip Macs it runs the backend on the host (from Kristika Sedai's branch) |

### Backend

| File | Change |
|---|---|
| `backend/app/vision/pose_to_robot.py` | Optional hip-less mode: if the hips are not visible, the torso frame is built from the shoulders alone, assuming an upright torso |
| `backend/app/services/follow.py` | Optional gentle mode: slower commands, harder filtering, and a per-tick limit on how far any joint may move |
| `backend/app/api/routes/speaker.py` | `POST /speak` (OpenAI TTS). RPS no longer uses it, but the OpenAI call now runs in a thread: it used to block the whole server for about 2 s per line, delaying robot moves and the sim stream |
| `backend/app/api/routes/state.py` | `POST /follow/hipless-arms` switches both modes on or off; `GET /joint_states/pulses` returns the robot's pose in servo pulses |
| `backend/app/services/follow.py`, `api/routes/websocket.py`, `services/intent.py` | Follow remembers which WebSocket started it, and only that connection's disconnect stops it. Before, any connection closing (a stale tab, a hot reload) stopped a newer page's follow |

Both backend modes are **off by default**, so the main demo behaves exactly as before. The Learn screen turns them on when it opens and off when it closes.

---

## 4. Running it

```bash
./run.sh
```

Open <http://localhost:5173> and click **Rock Paper Scissors**.

- Start Docker first (Docker Desktop on a Mac). If it isn't running, `run.sh` stops with `failed to connect to the docker API ... docker.sock: no such file or directory`.
- On an Apple-chip Mac, `run.sh` runs the backend on the host with `uv run server`, logging to `logs/backend.log`. Postgres and the frontend stay in Docker. The reason: mediapipe has no Linux-ARM wheel, so the backend image only builds for Intel, and under emulation MuJoCo returns wrong-length quaternions (known issue 15). On other machines the backend stays in Docker.
- Ctrl+C stops everything, including the host backend and the vision server.
- Simulation mode is enough. No robot is needed.
- CORAL's voice is the browser's speech synthesis, so the game speaks without `OPENAI_API_KEY`. The browser may block speech until the page has been clicked once.
- Restart the backend after pulling these changes. The new endpoints do not exist in an already-running server, and the follow behaviour will not change until it restarts.
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
| Change when CORAL starts its move | `THROW_AT` in `pages/RpsPlay.tsx` |
| Change how calm the similarity bars are (Learn) or how quickly a move card lights up (Play) | `SMOOTH_MS`, `SHOW_EVERY_MS`, `SHOW_STEP`, `SHOW_DEADBAND` in `rps/useSmoothedScores.ts` |
| Change where the child must stand | `TOO_CLOSE`, `TOO_FAR`, `CENTRE_SLACK` in `rps/bodyFit.ts` |
| Change the similarity rings | `ScoreRing` and `scoreColor` in `pages/RpsPlay.tsx` (green at `MATCH`) |
| Change CORAL's wave, reactions or dance | Pulse sets in `rps/coralMoves.ts` (arms and head only) |
| Change CORAL's colour or the stage lighting | `STAGE_*` colours and the `stage` branch of `components/RobotViewer.tsx` |
| Change the move colours or pictures | `MOVE_COLOR` and the drawing in `rps/PoseArt.tsx` (drawn from each gesture's `figure`) |
| Change CORAL's lines | `ROUND_LINE`, `FIT_LINE`, `finalLine` in `pages/RpsPlay.tsx` |
| Change how CORAL sounds | `VOICE_NAMES` and `RATE` in `audio/speech.ts` (`say -v '?'` lists the Mac's voices) |
| Change how long to hold when recording | `STILL_MS`, `STILL_TOLERANCE`, `MAX_HOLD_MS` in `pages/RpsCustom.tsx`; `HOLD_MS` in `gestures/useHoldStill.ts` for Gesture Studio |
| Change when the robot counts as caught up | `SETTLE_PULSES`, `SETTLE_MS` in `rps/useRobotSettle.ts` |
| Use real screenshots in view 1 | Add `rock.png`, `paper.png`, `scissors.png` to `frontend/public/rps/` |
| Change how fast the simulated robot follows | `_GENTLE_*` constants at the top of `backend/app/services/follow.py` |
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

1. **CORAL's Rock doesn't cross its arms.** (2026-10-29) Arms straight forward at shoulder height (`sho_pitch` 500), roll and elbow bend as in the stand pose, with the elbows twisted in (`el_pitch` 650/350) so the forearms angle toward each other; tuned by hand. It lands fully (collision check: not clamped). A real cross isn't practical: the forearms are long for the body, so the collision check stops them before they pass each other, and a stepwise path to a cross was tried and dropped as too slow and odd-looking.
2. **Detection thresholds are estimates.** They were checked with synthetic data only (ideal poses plus noise, and everyday poses such as arms down and hands on hips). With realistic landmark jitter the three gestures were recognised 96 to 100% of the time in that test. They have not been validated with real children. Expect to tune `minSimilarity` for Learn; the game uses best match.
3. **Arms pointing at the camera look like rock** in a 2D image (similarity about 0.70). `minSimilarity` is set to 0.72 to keep this out, which makes detection fairly strict.
4. **Gentle follow mode** was checked in the simulator and the speed was judged good, with no toppling. It has **not** been tried on the physical robot, so re-check the `_GENTLE_*` values before using it there.
5. **Hip-less mode assumes an upright torso.** If the child leans a lot, the arm angles will be off.
6. **The follow settings are global state in the main server process**, switched by `POST /follow/hipless-arms`. Two Learn screens open at once, or a crash that skips the cleanup request, can leave them on. Restarting the backend resets them. There is also only one follower: the newest page to ask for it owns it.
7. **Robot motion in the game is simulator-only.** `POST /set-pose` with `duration_ms` glides there in the sim only, after the collision and fall checks; a pose the fall check blocks simply doesn't move (`poseRobot` doesn't report it). Running this on the physical robot would need the `/move` route or similar.
8. **Each round starts with `/reset`**, which drops the robot straight into the stand pose rather than easing there. It has looked fine in the simulator.
9. **`poseRobot` calls are not cancellable.** Two overlapping calls interpolate the same joints at once until the older finishes. The game never overlaps them; Gesture Studio's fine-tuning can, briefly.
10. **The robot-caught-up limits** (60 pulses over 0.8 s) were set from one adult sitting at a desk. Check them with children standing.
11. **Nothing is stored yet**: no student ID, no per-round log, no screen recording, no pre-training quiz. Sayali asked to wait for the PIs (meeting on 2026-10-13). Each round already computes `similarity` and `reactionMs` for when logging is added.
12. **The 3D viewer sometimes stays blank in an embedded preview** until the window is resized. This was seen only in the Claude preview pane, not in Chrome.
13. **No automated tests.** The frontend has no test runner. The matcher is a pure function and is easy to unit-test if one is added.
14. **Voice depends on the computer.** Samantha comes with macOS; elsewhere the browser falls back to another local English voice, or stays silent if it has none. Chrome also refuses to speak before the page has had a click, so a page opened directly by URL may miss its first line.
15. **The backend in Docker on an Apple-chip Mac gets rotations wrong.** That image is Intel-only and runs under emulation, where MuJoCo 3.6's `mju_mat2Quat` returns quaternions with the right direction but the wrong length for some large rotations (a 120° turn about Y came out with length 2.0). three.js reads that as scale, so the robot showed huge stretched grey slabs. `RobotViewer.tsx` now normalizes every quaternion, and `run.sh` avoids emulation by running the backend on the host. The bad values come from the per-frame conversion in `mujoco_sim.py` (`mju_mat2Quat` on `geom_xmat`), so any other client of `/ws/sim` on an emulated backend would also need to normalize.
16. **`run.sh` is untested on an Intel Mac and on Linux** since the Apple-chip change. Those paths should be unchanged (the whole stack in Docker), but nobody has run them.
17. **CORAL's move is visible before the child shoots.** It starts at Paper, so a quick child could see CORAL's arms and pick the winning move in the 1.8 s before Shoot. CORAL's pick is still random and doesn't see the child. If this matters for the study, start at Scissors (`THROW_AT`), at the cost of CORAL arriving later.
18. **Kristika's branch `rps-redesign-ui-robot-test`** also has `tests/test_hardware_controller_positions.py`, which was left out: its import path is wrong (`robot.hardware_controller`), and with that fixed 2 of its 4 tests fail because the hardware-controller fix it tests isn't in the code. Ask her whether that fix is coming.
19. **The redesigned Play screen (2026-10-29) was checked only in a headless browser with simulated poses**, not with a real child or at six feet. Sizes, the placement thresholds in `rps/bodyFit.ts` and the sounds' volume need a check in the room. Sitting close is allowed, but Paper's arms span about four shoulder widths: once the shoulders are wider than about 22% of the frame the hands leave the picture and Paper gets no score at all (checked with simulated landmarks). The edge pulse and the "Step back a little so I can see your hands!" miss line are the only guard. CORAL's reactions are sim-only, like its moves (item 7).

### Ideas for next steps

- A body-pose-based classifier or a trained model if the rule-free similarity match proves too crude.
- Real photos for view 1.
