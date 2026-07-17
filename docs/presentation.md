# CORAL Voice AI Agent — Speaker Notes

---

## Slide 1: Voice AI Agent

**Speaker notes:**

Welcome everyone. This project is called CORAL — it stands for Cognitive Robot Autonomy and Learning, which is the lab this REU is affiliated with at Purdue. What I built this summer is a voice-driven AI agent that lets a child interact with a humanoid robot through natural speech and body movement.

The robot is the Hiwonder AiNex — a 24 degree-of-freedom humanoid with arms, legs, and a head. The system layers three modalities together: voice input processed by a local speech recognition model, computer vision tracking the user's body pose in real time, and a motion planning layer that translates language into physical servo commands.

The goal from the start was to make robot interaction feel natural enough for a child — no controllers, no programming, just talking and moving.

---

## Slide 2: Why This Project Exists

**Speaker notes:**

The core problem is that speech commands for robots are inherently ambiguous when it comes to spatial instructions. If a child says "put your arm like this," there's no reference point. But if you combine speech with the child's own body pose — which the camera sees in real time — you get a much richer grounding signal.

The workflow CORAL introduces is a three-step loop: the child physically demonstrates a pose, the system captures and maps it to robot joints, and then the child uses natural language to fine-tune it — "raise the arm a bit higher," "turn your head to the left." Once they're happy, they name the move and it's saved. So the child is genuinely co-authoring robot motion through a conversation, not just issuing commands.

This is grounded in child-robot interaction research — the age range we're targeting is roughly 3 to 8 years old, where interaction needs to feel like play rather than programming.

---

## Slide 3: Main System Components

**Speaker notes:**

The architecture has five main components that all talk to each other over HTTP and WebSockets.

The React frontend runs in the browser and handles everything the user sees — the live camera stream, the status indicators, voice recording, text input, and the final catalog of saved moves. The key file is `useProDemoMachine.ts`, which implements the guided demo as a state machine.

The FastAPI agent server is the brain — it runs on the laptop, receives audio from the browser, transcribes it with a local Whisper model, calls the LLM, resolves the motion plan, and dispatches commands to either the MuJoCo simulator or the physical robot. This is `server.py`.

The vision service is a separate FastAPI server that continuously reads camera frames, runs MediaPipe pose estimation, and maintains the latest body landmarks for retargeting. It also serves the camera stream as an MJPEG feed to the frontend.

The speaker server is intentionally simple and blocking — it uses pyttsx3 for text-to-speech on a dedicated port. The reason it's blocking is to keep the UI and audio synchronized, so the robot doesn't start moving before it finishes speaking.

On the robot side, a FastAPI server runs inside a Docker container on the Raspberry Pi. It receives HTTP requests from the laptop and translates them into ROS body-control commands that drive the physical servos.

---

## Slide 4: What The Agent Can Do

**Speaker notes:**

There are two primary interaction modes, but they share the same underlying WebSocket pipeline.

The first is open-ended voice control. The user speaks or types a command — "raise your right arm," "shake your head," "bend your elbow" — and the agent plans and executes the motion. The LLM handles the full range of phrasing a child might use, including relative adjustments like "a bit more" or "slower," and it tracks conversation history so corrections refer to the right joint.

The second mode is the guided pose-capture workflow. This is the main demo. The user has a free conversation with the robot, and when they say something like "capture my pose," the system switches into a structured capture flow. I'll walk through the specific steps on the next slide.

Both modes reuse the exact same WebSocket audio pipeline and LLM motion planner — the difference is just in how the frontend orchestrates the overall session and what triggers a pose capture.

---

## Slide 5: Guided Pose-Capture Loop

**Speaker notes:**

The guided workflow is a five-step loop implemented as an XState state machine in the frontend.

It starts in the ADJUST step — an open conversation where the child can talk to the robot freely and watch it respond. This is also where they can ask the robot to make a starting pose.

When the user says "capture my pose" — or any phrase close to it — the frontend triggers the COUNTDOWN step. The UI instantly locks the robot's current state so it doesn't change during capture, then runs a 3-2-1 countdown to give the user time to strike and hold their pose.

The CAPTURE step then grabs the most stable pose frame from the vision server — we pick the frame with the best landmark confidence — and calls the `/map-features` endpoint to translate MediaPipe body landmarks into robot joint targets. The robot immediately executes the resulting motion.

The user then enters the REFINE step, where they keep talking to fine-tune the pose — "lower my right arm a bit," "tilt your head up." Each voice command goes through the full LLM pipeline and updates the robot's position incrementally.

Finally, the NAME step lets the user assign a name to the finished move. The joint coordinates are saved to a SQLite database, and the loop returns to ADJUST for the next round.

---

## Slide 6: How Spoken Commands Become Robot Motion

**Speaker notes:**

Let me walk through what actually happens between the moment you speak and the robot moving.

First, the browser records your utterance as a WebM audio blob and streams it over a WebSocket connection to the agent server. This is handled in `api.ts` on the frontend.

The agent server passes the audio to a local faster-whisper instance running on CPU — no cloud API calls, so there's no latency from a round trip to an external transcription service. The transcription, along with the robot's current joint state in degrees, any saved poses from this session, and the recent conversation history, all get assembled into a single prompt for the LLM.

The LLM — currently GPT-4o-mini — returns a JSON object. Here's what a real response actually looks like for something like "raise your right arm":

```json
{
  "action": "motion",
  "waypoints": [
    {
      "primitives": ["right_arm_forward"],
      "angle": 90,
      "direction": null,
      "speed": 1.0
    }
  ],
  "verbal_response": "Raising my right arm up 90 degrees. Let me know if that's the right angle.",
  "satisfied": null
}
```

The `waypoints` array contains named motion primitives with degree angles and speed. Multiple primitives in one waypoint entry execute simultaneously. The server resolves each primitive name into actual joint radian values, validates them against joint limits, converts to servo units on a 0–1000 scale, and dispatches to the simulator and/or physical robot.

---

## Slide 7: LLM Output Is Constrained by Motion Primitives

**Speaker notes:**

One of the key safety decisions in this system is that the LLM cannot send arbitrary motor commands. Instead, it selects from a fixed library of named primitives — functions that take an angle in degrees, an optional direction, and a speed, and return validated joint targets in radians.

The table on the slide shows the primitives in their simplified form. In the actual codebase each one has a left and right variant — so `arm_forward` is really `left_arm_forward` and `right_arm_forward`, each driving the corresponding shoulder pitch joint.

`arm_out` is the sideways abduction motion — arms out to the sides like a T-pose. `arm_forward` is forward/up flexion — like raising your arm to point at something. The distinction matters because they map to different joints: roll versus pitch on the shoulder.

All angle inputs are specified in degrees by the LLM, which makes the prompt much easier to reason about. The server converts them to radians and clamps them to ±2.09 radians — roughly ±119 degrees — which is the joint limit from the MuJoCo model. The safe limit shown for each primitive reflects the usable input range.

A parallel tracks feature also allows two independent body part sequences to run concurrently — for example, shaking the head while pumping an arm up and down.

---

## Slide 8: How the Robot Mimics the User's Pose

**Speaker notes:**

The pose retargeting pipeline is what makes the "show me a pose" interaction work.

The vision server continuously processes camera frames with MediaPipe Pose, extracting 33 body landmarks in 3D. The key endpoint is `/map-features`, which takes a snapshot of the latest stable frame and converts those landmarks into robot joint targets.

The core challenge is that raw MediaPipe coordinates are in camera space — if the user rotates or moves, all the coordinates shift. To fix this, we compute arm angles in a torso-local coordinate frame anchored to the midpoint between the hips and shoulders. This way, the arm angles we compute reflect the user's body geometry, not the camera angle.

Mirror mode is also applied: the user's right arm maps to the robot's left arm and vice versa. This feels natural because the robot is facing you — it mirrors you like a reflection, not like a copy.

One safety constraint is that capture is rejected if the user's hips aren't visible in the frame. The hip landmarks anchor the torso-local coordinate frame, so without them the arm angle math becomes unreliable.

---

## Slide 9: From Joint Targets to Safe Servo Movement

**Speaker notes:**

Once we have joint targets in radians, there are four steps to get them onto the physical hardware.

First, the joint targets are scaled to Hiwonder servo units. The AiNex uses a 0–1000 integer scale where 500 is the neutral center position. Speed is converted to a movement duration in milliseconds — a higher speed value means a shorter duration and faster motion.

Second, the collision checker can perform a shadow rollout. Before actually sending commands to the robot, it runs the planned motion forward in MuJoCo in a temporary copy of the simulation. If the rollout detects a self-collision — arms crossing, elbow hitting the torso — it backs off the motion before it's ever dispatched. This is optional and can be disabled with an environment variable.

Third, hardware-level limits clamp servo commands. Two servos have special limits: the left elbow yaw is capped at 600 out of 1000, and the right elbow yaw — which is a physically damaged servo — is constrained between 360 and 850 to prevent mechanical strain.

Fourth, in physical robot mode, the final servo commands go over HTTP to the Pi server, which calls the ROS MotionManager to drive the actual servo bus.

---

## Slide 10: Interactive UI Storyboard

**Speaker notes:**

The frontend has three main visual states during a session.

The live feed panel shows the camera stream with MediaPipe annotations overlaid — you can see the body landmarks in real time. Below the feed is the status indicator, which cycles through LISTENING, TRANSCRIBING, THINKING, and ACTION APPLIED as the pipeline processes each utterance.

When a capture is triggered and the pose is locked, the view switches to the captured frame panel. You see the static pose image with a FRAME_LOCKED badge, and the status shows THINKING while pose processing runs.

Once the session is complete and all moves are named, the saved move catalog appears — a grid of stick figure thumbnails, one per named move, showing the captured pose geometry. These are generated from the MediaPipe landmarks at capture time.

The backend also saves the joint coordinates to SQLite, so the named moves persist for the duration of the server session and can be replayed on command.

---

## Slide 11: How the System Keeps Context

**Speaker notes:**

Context persistence operates at three levels.

At the session level, each WebSocket connection maintains a short-term conversation memory — a sliding window of recent user and assistant turns that gets included in every LLM prompt. This is what allows corrections like "a little more" or "actually, the other arm" to work correctly — the model knows what was just moved.

The backend also maintains a SQLite database of saved poses. When the user names a move, the current joint state in radians is written to the database. On future turns, the list of saved pose names is injected into the LLM prompt, so the user can say "do the warrior pose again" and the model can look it up and replay it directly.

For observability, Langfuse tracing records every LLM call — inputs, outputs, token counts, cache hit rates, and latency. Every session also writes a complete JSON file of all interactions to disk, which I use for replaying and debugging edge cases.

---

## Slide 12: What Works Now

**Speaker notes:**

Here's an honest assessment of where the system stands.

On the working side: voice and text commands reliably drive the head, arm, and elbow primitives. The full guided pose-capture workflow — adjust, countdown, capture, refine, name, review — runs end to end. Pose retargeting works in simulation and on the physical Pi, with hardware-calibrated servo pulses to account for the robot's actual joint geometry.

The main technical limitations right now: the robot can occasionally make sudden sharp movements, especially when a large angle change is commanded at high speed. The collision checker helps but doesn't catch all cases. Leg joints are not yet retargeted from human pose — the legs stay in the standing position throughout. A few joints need physical calibration on the hardware unit we have. And voice-based pose refinement — where you say "raise it five degrees" after a capture — still needs more prompt tuning to be reliable.

These are all solvable, and they represent the clearest directions for continued work on this project.

---
