# Human-to-Robot Pose Experiment

**Objective.** Quantify how accurately the end-to-end pipeline (webcam → MediaPipe → retargeting → servos) reproduces a human arm pose on the physical robot.

**Rationale.** Measuring a person's true anatomical joint angles precisely is impractical. Instead we use a small set of poses that a person can strike unambiguously without instrumentation, so the instructed (nominal) angle is itself trusted ground truth. Accuracy is then the error between that nominal human angle and the angle the robot actually holds.

**Poses (3).** Each is held with both arms:

1. Arms down at the sides.
2. Arms overhead, straight up.
3. Muscles — upper arms horizontal out to the sides, elbows bent 90° (biceps flex).

**Measured angles (3 per arm).** All defined in the robot's own frame:

1. **Arm elevation** — angle between the upper arm and the downward vertical, read in the frontal plane (viewed from the front). 0° = arm down, 90° = horizontal, 180° = overhead.
2. **Arm depth (yaw)** — how far the upper arm is rotated forward out of the frontal plane, viewed from directly above. 0° = arm in the frontal plane (out to the side / up / down), +90° = pointing straight forward (toward the camera). All three poses have a nominal depth of 0°, so this axis measures the robot's forward/back deviation from the intended plane.
3. **Elbow bend** — flexion at the elbow only, independent of any plane. 0° = straight, 90° = right angle.

**Apparatus.** Mac webcam → MediaPipe pose landmarks → torso-frame retargeting → servo commands, executed on the Hiwonder AiNex through the same `/map-features` → `/move` path the live demo uses (self-collision clamp and fall check included). Driven from the `/experiment` "Joint Angle" tester mode.

**Procedure (per trial).** The demonstrator strikes the cued pose; the system captures a frame, retargets it, and drives the robot. Once the robot settles, the operator measures the three angles on the physical robot with a protractor and records them. The tester logs, per arm: the nominal, the CV estimate (est, diagnostic only), the retargeted target (mapped), the post-safety applied pose (applied), and the operator's protractor reading (robot).

This experiment can run using the code in the tag "joint-angle-v1" (SHA 580b1420) https://github.com/Ethanxu1/coral-voice-ai-agent-reu/

**Design.** 3 poses × 3 repetitions = 9 trials in randomized order (seeded). Both robot arms are measured each trial → 54 angle measurements per session.

**Measurement protocol.** With a protractor: for the elbow, lay it along the servo/arm edge and trace the angle the forearm makes; for the two planar angles, align the protractor to the plane and sight down/through it. Readings are rounded to the nearest 5° because finer precision is not reliably readable on the robot.

**Statistic.** Per angle, the error is |robot protractor reading − nominal human angle|, aggregated as mean absolute error per angle and per pose. This is an end-to-end error (perception + retargeting + servo/mechanical), not an isolated CV error.

**Limitations.**

* Protractor readings rounded to 5°.
* Single camera viewpoint.
* Overhead demands ~180° of shoulder elevation, which can hit the servo's range limit; such trials are flagged (joint_limit_clamped) and their error reflects mechanical ROM, not perception.
* The safety layer can pull back or block a pose; trials where it fired (collision_clamped, fall_blocked, safe_fraction < 1) should be flagged or excluded.
* Movements that point the subject's arms into the screen do not reliably trigger any motion, given that the code currently excludes low