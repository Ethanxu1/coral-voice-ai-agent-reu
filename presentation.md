# CORAL Voice AI Agent: Slide Presentation Outline

## Slide 1: Project Title

**Title:** CORAL Voice AI Agent  
**Subtitle:** Multimodal child-robot interaction for the Hiwonder AiNex humanoid robot

**Key points:**
- Voice, vision, and robot motion are combined into one interactive demo system.
- The system supports both open-ended robot control and a structured pose-capture workflow.

**Visual placeholder:** Photo or screenshot of the AiNex robot beside the Coral UI.

---

## Slide 2: Problem and Goal

**Title:** Why This Project Exists

**Key points:**
- Children need natural ways to communicate desired robot poses and motion.
- Speech alone can be ambiguous; body pose gives another grounding signal.
- CORAL explores a workflow where a child can show a pose, refine it with language, and save it as a named move.

**Visual placeholder:** Simple "child speaks + poses -> robot responds" diagram.

---

## Slide 3: System Overview

**Title:** Main System Components

**Key points:**
- React frontend runs the guided demo and displays camera, status, transcript, and captured moves.
- FastAPI agent server handles Whisper transcription, LLM motion planning, simulation, and hardware dispatch.
- Vision service reads camera frames, MediaPipe landmarks, head pose, and pose retargeting.
- Robot server on the Pi bridges HTTP requests to ROS body-control services.
- Speaker server provides blocking text-to-speech so UI timing stays synchronized.

**Visual placeholder:** Architecture block diagram:
Frontend -> Agent Server / Vision Server / Speaker Server -> Pi Robot Server -> ROS body service -> AiNex servos.

**Code references:** `frontend/src/demo/useProDemoMachine.ts`, `src/coral_agent/server.py`, `src/coral_agent/vision/vision_server.py`, `src/coral_agent/robot/pi/nodes/robot_server.py`, `src/coral_agent/speaker/speaker_server.py`

---

## Slide 4: Two Main Interaction Modes

**Title:** What CORAL Can Do

**Key points:**
- **Open-ended voice control:** user speaks or types a command; the robot plans and executes motion.
- **Pro demo pose workflow:** user talks freely, says "capture my pose," the system maps their pose to robot joints, then supports language-based refinement.
- Both modes reuse the same WebSocket action pipeline for speech/text to robot motion.

**Visual placeholder:** Split-screen workflow graphic: "Voice command" path and "Pose capture + refinement" path.

---

## Slide 5: Pro Demo Workflow

**Title:** Guided Pose-Capture Loop

**Key points:**
- The demo starts in an adjustment conversation where the user can speak freely.
- Capture is triggered by phrases like "capture my pose."
- The UI locks the robot state, runs a 3-2-1 countdown, captures the latest pose, maps it to robot commands, and executes them.
- The user then refines the robot pose with voice or text until satisfied.
- Finally, the user names the move and the loop repeats until all rounds are complete.

**Visual placeholder:** State-machine flow:
ADJUST -> COUNTDOWN -> LOADING -> ADJUST/refine -> NAME -> next round -> DONE.

**Code references:** `frontend/src/demo/useProDemoMachine.ts`

---

## Slide 6: Voice-to-Motion Pipeline

**Title:** How Spoken Commands Become Robot Motion

**Key points:**
- Browser records one utterance and sends WebM audio over WebSocket.
- Agent server transcribes audio with local `faster-whisper`.
- The LLM receives current robot state, saved poses, conversation memory, and the user request.
- The LLM returns JSON with a short spoken response, waypoints, and satisfaction status.
- Waypoints are resolved into joint targets, validated, converted to servo commands, and dispatched.

**Visual placeholder:** Pipeline diagram:
Mic -> WebSocket -> Whisper -> LLM JSON -> primitives -> validation -> servo commands -> robot/sim.

**Code references:** `frontend/src/demo/api.ts`, `src/coral_agent/server.py`, `src/coral_agent/prompts/router.md`

---

## Slide 7: Motion Planning Details

**Title:** LLM Output Is Constrained by Motion Primitives

**Key points:**
- The LLM does not directly send arbitrary motor commands.
- It selects named primitives such as arm forward, arm out, elbow bend, elbow rotate, head turn, head tilt, or neutral.
- Angles are specified in degrees, then converted to radians and clamped to joint limits.
- Multiple primitives can be merged into one waypoint for simultaneous motion.
- Parallel tracks are supported when separate body parts need independent sequences.

**Visual placeholder:** Table of representative primitives and mapped joints.

**Code references:** `src/coral_agent/primitives.py`, `src/coral_agent/prompts/router.md`, `src/coral_agent/validation.py`

---

## Slide 8: Pose Retargeting

**Title:** How the Robot Mimics the User's Pose

**Key points:**
- The vision server keeps the latest camera frame, body landmarks, and head pose.
- `/map-features` converts MediaPipe landmarks into robot joint targets.
- The mapping uses a torso-local coordinate frame so arm angles are based on body geometry rather than camera orientation.
- Mirror mode maps the user's right side to the robot's left side, making the robot feel like it is facing the user.
- If hips are not visible, capture is rejected because arm retargeting needs a reliable torso frame.

**Visual placeholder:** Annotated pose image showing shoulders, elbows, wrists, hips, and mirrored robot arms.

**Code references:** `src/coral_agent/vision/vision_server.py`, `src/coral_agent/vision/pose_to_robot.py`

---

## Slide 9: Robot Execution and Safety

**Title:** From Joint Targets to Safe Servo Movement

**Key points:**
- Joint targets are converted to Hiwonder servo units on a 0-1000 scale.
- Speed is converted into movement duration.
- In simulation mode, MuJoCo receives the commands and interpolates joint motion.
- In robot mode, commands are sent over HTTP to the Pi robot server and then through ROS body commands.
- A collision checker can shadow-rollout the motion in MuJoCo and back off before self-collision.
- Hardware-side limits clamp servo commands, including special limits for damaged or risky servos.

**Visual placeholder:** Graph or diagram of angle -> servo pulse -> movement duration; optional collision-check rollout graphic.

**Code references:** `src/coral_agent/robot/angle_utils.py`, `src/coral_agent/server.py`, `src/coral_agent/collision_checker.py`, `src/coral_agent/robot/pi/nodes/robot_server.py`

---

## Slide 10: Frontend Experience

**Title:** What the User Sees

**Key points:**
- The main demo view shows the live camera stream or the captured frame.
- Status changes between listening, transcribing, thinking, action applied, and clarification.
- The UI supports both voice and text input.
- Finished sessions display saved move cards with pose images and names.

**Visual placeholder:** Screenshot sequence:
Live stream, countdown, captured pose/refinement, final results grid.

**Code references:** `frontend/src/pages/ProDemo.tsx`, `frontend/src/demo/api.ts`

---

## Slide 11: Data and Observability

**Title:** How the System Keeps Context

**Key points:**
- Each WebSocket action session keeps short-term conversation memory for iterative refinement.
- The Pro Demo stores named move cards in frontend state for the final review screen.
- The backend also has a separate "save current pose" voice flow that stores joint states in SQLite for the current server session.
- Conversations are recorded to JSON files for debugging.
- Langfuse tracing records LLM calls and action history.

**Visual placeholder:** Example trace/log screenshot or simplified memory diagram.

**Code references:** `src/coral_agent/server.py`, `src/coral_agent/pose_db.py`

---

## Slide 12: Current Capabilities and Limitations

**Title:** What Works Now

**Key points:**
- Voice or text commands can drive head, arm, and elbow primitives.
- Human pose capture can retarget arms and head in simulation; on Pi, pose retargeting uses hardware-calibrated servo pulses.
- Backend system intents can start live follow mode, stop follow mode, trigger one-shot pose capture, or save the current robot pose.
- The guided workflow supports capture, retake, refinement, naming, and final review.
- The physical robot path includes state locking, ROS body-command execution, and servo clamping.

**Limitations:**
- Retargeting depends on visible hips, shoulders, elbows, and wrists.
- Legs are not currently retargeted from human pose.
- Head pose is included in the Mac vision path, but the Pi `/map-features` path leaves head targets neutral.
- The MobileNetV3 classifier still exists, but the active pose-mimicry path uses landmark retargeting instead.

**Visual placeholder:** Capability matrix: Voice, pose retargeting, simulation, physical robot, saved poses, safety checks.

---

## Slide 13: Suggested Demo Walkthrough

**Title:** Live Demo Script

**Key points:**
- Start on the Pro Demo screen.
- Ask Coral to make a simple motion, such as raising an arm.
- Say "capture my pose" and hold a clear full-body pose.
- Let the robot mimic the pose.
- Refine with a command like "raise the left arm higher" or "turn your head left."
- Say "looks good," name the move, and show the results grid.

**Visual placeholder:** Timeline with screenshots from each live demo step.

---

## Slide 14: Takeaways

**Title:** Key Contributions

**Key points:**
- CORAL combines speech, vision, simulation, and physical robot control in one workflow.
- The system grounds language in the robot's current state and motion primitives.
- Pose retargeting lets the child demonstrate motion directly instead of only describing it.
- The architecture separates UI, AI planning, vision, speech, simulation, and hardware execution so each piece can be improved independently.

**Visual placeholder:** Final system summary diagram or photo of robot performing a captured pose.
