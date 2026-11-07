# Pose Designer: Handover

A child makes their own robot pose: CORAL copies them (from a camera snapshot, or by following them and freezing), then they refine the pose by talking ("lift your right arm higher", "that's a bit too much", "yes"), and type a name. Saved poses show up as moves in the [Dance Game](dance-game.md).

For setup and running the stack, see the [README](../README.md).

---

## 1. What it does

Entry point: **⭐ Design a Pose** on the home page (`/`), route `/pose-designer`. Any page can link to it with `navigate('/pose-designer', { state: { from: '/somewhere' } })`; when the child saves (or presses Back on the first screen) it returns to `from`, or to `/` if there is none.

1. **Choose**: two cards, **Copy my pose** (camera snapshot) or **Follow me** (CORAL mirrors the child live).
2. **Capture**: camera on the left, CORAL on the right. **Take picture** / **Freeze!** starts a 5-second countdown (time to step back and pose), then snaps the camera or stops following. While following, saying **"save this pose"** (or "freeze!", "save it", "keep this one") freezes straight away, with no countdown, on the pose held when the child started saying it. Either way the robot ends up in the child's arm pose with the legs and head in the normal stand. The snapshot only needs the shoulders and arms in frame, not the hips.
3. **Refine**: CORAL on the left; on the right only CORAL's **last message**, what it heard last, and the mic state (no chat log). When CORAL proposes a change, a see-through teal **ghost** of the changed arm appears over the robot, with chips like "Right arm forward/up +10°" and 👍 Yes / 👎 No buttons. The robot only moves when the child says yes (or taps Yes). A small text box lets a grown-up type instead of speaking. **I'm done** (or saying "I'm done") goes to naming.
4. **Name**: the child types a name (max 24 characters) and presses **Save ⭐**.

Example:

| Child | CORAL | Screen |
|---|---|---|
| "Can you lift your right arm up some more?" | "I'll lift my right arm up by 20 degrees. How's that?" | ghost arm 20° higher |
| "That's a bit too much." | "I'll lift my right arm up by 10 degrees instead." | ghost moves to 10° |
| "Yes." | "Here I go!" | robot glides there, ghost gone |

---

## 2. How it works

```
PoseDesigner.tsx (steps, capture, naming)
  ├─ poseDesigner/capture.ts        snapshot: /map-features -> /move ; follow: rps startFollowing/stopFollowing
  ├─ poseDesigner/useDesignConversation.ts
  │     mic (audio/capture.ts) -> Whisper (/ws transcribe_only) -> POST /pose-design/turn -> speak()
  │     proposal -> POST /pose-design/preview -> RobotViewer ghost
  │     yes -> POST /set-pose (glide, collision + fall check, wait until arrived)
  └─ poseDesigner/customPoses.ts    localStorage "coral.customPoses" -> Dance Game shelf
```

### "Save this pose" while following (`waitForSaveCommand`, `poseDesigner/capture.ts`)

The mic listens the whole time CORAL follows (it keeps listening while each utterance is transcribed). When speech starts it reads the robot's pose (`captureUtterance` `onSpeechStart` → `/joint_states/pulses`). Each transcript goes to `POST /pose-design/save-command`, a regex (`is_save_command` in `services/pose_design.py`, no LLM, so it answers at once). On a match the page stops following and keeps the pose from when the child started speaking.

### One LLM turn per utterance (`backend/app/services/pose_design.py`)

No regex classifier in refine: each thing the child says is one LLM call (`LLM_MODEL`, strict JSON schema) that returns

- `action`: `propose` (change the pose), `accept` (yes to the waiting proposal), `reject` (no), `done` (finished), or `chat` (anything else, including things CORAL can't do);
- `reply`: what CORAL says, spoken by the browser's speech synthesis;
- `changes`: for `propose`, the **whole** proposal measured from the current pose. Because it replaces the waiting proposal rather than adding to it, "that's too much" simply re-proposes a smaller number.

The model sees the current pose, the waiting proposal and the last 12 messages. Prompt: `backend/app/llm/prompts/pose_design.md`.

### Controls

The LLM never sees servo pulses. It works in eight "controls", degrees from the standing rest, where positive means the same on both arms:

| Control | Joint | Positive means |
|---|---|---|
| `left/right_arm_forward` | `*_sho_pitch` | swing the arm forward and up (≈90 straight ahead, ≈160 up) |
| `left/right_arm_out` | `*_sho_roll` | lift the arm out to the side (≈75 is a T) |
| `left/right_elbow_bend` | `*_el_yaw` | bend the elbow more |
| `left/right_forearm_out` | `*_el_pitch` | swing the bent forearm away from the body |

Arms only: the physical robot has no head servos, and leg changes can tip it over. The server clamps every proposal to the joint safe ranges (`robot_params.JOINT_SAFE_RANGES`) and reports only the part that can really happen; if nothing can, CORAL says it can't move that way any further. `backend/tests/test_pose_design.py` checks in the simulator that each control moves the hand the way its description says.

### The ghost

`POST /pose-design/preview` poses the proposed arm joints on a scratch copy of the live simulation (`AiNexSimulator.get_geom_poses(preview=...)`) and returns every link's position in the same layout `/ws/sim` streams. `RobotViewer`'s `ghost` prop draws translucent teal copies of only the links that would move.

---

## 3. File map

| File | Purpose |
|---|---|
| `frontend/src/pages/PoseDesigner.tsx`, `.css` | The page (reuses the Dance Game's look from `DanceGame.css`) |
| `frontend/src/poseDesigner/useDesignConversation.ts` | Listen → turn → speak loop, proposal, ghost, applying a yes |
| `frontend/src/poseDesigner/capture.ts` | Snapshot capture, "save this pose" listener, reading the robot's pose after capture |
| `frontend/src/poseDesigner/customPoses.ts` | Saved poses in localStorage |
| `frontend/src/api/poseDesign.ts` | `designTurn`, `previewPose` |
| `frontend/src/components/RobotViewer.tsx` | `ghost` prop |
| `frontend/src/rps/useRobotFollow.ts` | `startFollowing` / `stopFollowing` (shared with RPS) |
| `backend/app/services/pose_design.py` | Controls, clamping, the LLM turn |
| `backend/app/api/routes/pose_design.py` | `/pose-design/turn`, `/pose-design/save-command`, `/pose-design/preview` |
| `backend/app/llm/prompts/pose_design.md` | The prompt |

---

## 4. Known issues and open items

1. **The LLM sometimes over-applies "both arms".** With one arm raised and one hanging, "lower both arms" occasionally also swings the hanging arm back a little. The ghost shows it and the child can say no; a bigger model (`LLM_MODEL`) or a code-side rule would fix it.
2. **Follow me wasn't tested end to end here** (it needs the camera and vision server). It uses the same follow pipeline as RPS "Make your own moves".
3. **Poses are stored per browser** (localStorage). There's no way to rename or delete one yet, and they don't reach the backend's pose library.
4. **Sim only.** Accepted changes and Dance Game playback don't use `to_robot`.
5. **The right elbow can't bend past the standing pose** (damaged servo, range 450-850), so "bend your right elbow" gets "I can't move that way".
6. **Follow: the right elbow stops at a 90° bend.** `r_el_yaw` is capped at the stand pulse (damaged servo, safe range 450-850), so bending the child's elbow past 90° moves the robot's left forearm but not its right one. Follow has no collision rerouting; this cap is the only left/right difference (checked in the sim with mirrored targets).
7. **"Lift your arm higher" with no side**: if both arms are equally plausible, CORAL asks which arm (prompt rule) instead of moving.
8. **No frontend tests** (no runner). The backend side is covered by `backend/tests/test_pose_design.py`.
