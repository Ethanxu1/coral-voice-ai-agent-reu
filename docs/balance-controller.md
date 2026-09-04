# Balance Controller — Design Plan

Goal: while the robot mirrors a child's movements (the existing follow/mimicry
pipeline — [`follow_controller.py`](../backend/app/follow_controller.py) →
[`pose_to_robot.py`](../backend/app/vision/pose_to_robot.py)), it should
actively keep itself upright instead of just holding whatever joint targets
retargeting produced, and it should tell the child out loud when a requested
pose is beyond what the robot can physically do — rather than silently
clamping or silently doing nothing.

This is a plan, not a changelog — nothing described here is implemented yet.
Background and the reasoning behind these choices is in this session's prior
turns; this doc is the actionable version of that discussion.

## 1. What's needed from you (hardware side)

These are one-time or occasional physical steps — not ongoing maintenance.

1. **Weigh the robot** (kitchen/postal scale). The sim's summed link masses
   come to 2.3475 kg (traced to the manufacturer's own CAD export — see
   below); your number will be higher because the model has no battery,
   wiring, or fastener mass. The gap between your measurement and 2.3475 kg
   is roughly "what to add back."
2. **Correct `body_link`'s mass in [`ainex.xml`](../assets/ainex/ainex.xml)**
   for that missing mass, positioned where the battery actually sits in the
   torso (a caliper/eyeball estimate of its mounting offset is enough — this
   doesn't need to be exact, just closer than "missing entirely"). One-time
   edit.
3. **Confirm the onboard IMU works on your unit.** The physical robot's
   control board already has one — no sensor to buy or wire. SSH into the
   Pi and run the manufacturer's own test script
   (`ainex_sdk/board_sensor_check.py` in the
   [ainex-robot-code](https://github.com/lalalune/ainex-robot-code) source —
   your robot's ROS workspace should already have an equivalent installed)
   and confirm it prints live values when you tilt the robot. Note whether
   you get 6 floats back (accel + gyro) or 9 (+ magnetometer) — that decides
   whether you get a heading estimate for free.
4. **Two-scale balance check**, to validate the corrected mass model: stand
   the robot on two bathroom scales, one foot on each, in its `stand` pose.
   The left/right split validates lateral CoM; total confirms your scale
   measurement from step 1. This is a validation check on the model, not
   itself an input to the controller.
5. **Once a first controller exists: a soft/matted test area.** Early gain
   tuning on real hardware means the robot *will* fall while you're finding
   safe gains — plan for a crash mat or carpet and be ready to catch it,
   especially once you get to single-leg testing.

Per-body-part disassembly and weighing is **not** needed — see §5.

## 2. What's already true about the hardware/software (context for the plan)

Found by tracing the manufacturer's own open-sourced stack
([lalalune/ainex-robot-code](https://github.com/lalalune/ainex-robot-code)),
not assumed:

- The mass/inertia values already in `ainex.xml` match the manufacturer's
  CAD-exported URDF exactly, link for link. They're not placeholders.
- The robot has **no foot pressure/force sensing** — nothing in the
  manufacturer's driver stack exposes it. Balance has to work off IMU
  (attitude + angular rate) alone; it cannot know true foot pressure or a
  measured center-of-pressure on the real robot the way the sim's
  `subtreecom`/foot-contact sensors can. Design for that constraint, don't
  assume it away.
- The manufacturer's own onboard software has **no closed-loop balance
  controller at all** — only an open-loop walking-gait pattern generator
  (`walking_param.yaml`: `y_swap_amplitude`, `z_swap_amplitude`,
  `pelvis_offset`, etc.) that runs during an active walk cycle and nothing
  else. Standing/single-leg balance is genuinely new work; there's no
  reference implementation to adapt.
- The servo bus's control cycle is 50 Hz
  (`servo_control_cycle: 0.02` in `walking_param.yaml`) — treat that as the
  realistic ceiling for how fast joint commands can actually update, not an
  assumption to verify from scratch.

## 3. Architecture

Two loops, running in different places, that must not fight each other:

```
                    ┌─────────────────────────────────────────┐
   laptop/backend   │  vision retarget → pose_to_robot.py      │
   (existing)       │  → JOINT_LIMITS clamp → target joints    │
                     └───────────────────┬───────────────────┘
                                         │ desired pose (what the
                                         │ child is doing)
                                         ▼
                     ┌─────────────────────────────────────────┐
   Pi (new)          │  balance loop — always running           │
                     │  reads: onboard IMU (attitude, rate)     │
                     │  reference: current desired pose         │
                     │  output: bounded ankle/hip offset added  │
                     │          on top of the desired pose      │
                     └───────────────────┬───────────────────┘
                                         ▼
                              servo bus (50 Hz ceiling)
```

**Ownership split**, to avoid the mimicry command and the balance correction
fighting over the same joints: the balance loop only ever adds a *bounded
offset* on top of whatever pose is currently commanded — it never replaces
retargeting's output. Ankle roll/pitch and hip roll/pitch are the correction
channels; every other joint (arms, head, grippers) is retargeting's alone,
untouched by balance. This means the balance loop needs to know the current
"desired" joint targets as its baseline, not just issue corrections in a
vacuum.

**Why the balance loop lives on the Pi, not the laptop:** established
earlier this session — the laptop↔Pi path is HTTP over Wi-Fi
(`docs/hardware.md` has a dedicated "Very high latency" troubleshooting
section), nowhere near fast enough for a reactive stabilization loop.
This mirrors a pattern already in the codebase: vision runs as its own
always-on background process on the Pi specifically so it doesn't compete
with request handling (`docs/overview.md`) — the balance loop should be
structured the same way, as its own persistent process/thread separate from
`robot_server.py`'s request handlers (which currently *block* until a move
finishes — a balance loop can't live inside that).

**Same algorithm, two sensor sources.** Build and tune the controller
against MuJoCo's sensors first (fast iteration, nothing physically at risk),
then run the identical control logic on the Pi against `get_imu()` instead.
Keep the boundary narrow — "read attitude + rate in, joint offset out" — so
swapping the data source doesn't mean rewriting the logic. This mirrors the
existing `RobotController` abstraction in this codebase
([`interface.py`](../backend/app/robot/interface.py):
`SimController`/`AiNexHardwareController` behind one interface) — same idea,
applied to the balance loop's sensor input instead of its actuator output.

## 4. The controller itself

**Sensing available on real hardware:** torso pitch/roll and angular rate
from the onboard IMU. No ground-truth CoM, no foot pressure. (Sim has both,
via `subtreecom` and the foot contact sensors already defined in
`ainex.xml` — useful for building intuition and cross-checking in
simulation, but the deployed controller can't depend on them.)

**Two-tier correction**, standard for this kind of balance problem:

1. **Ankle strategy** (primary, handles small disturbances): a PD term on
   measured torso pitch/roll error from vertical, output added directly to
   ankle pitch/roll as a bounded offset.
2. **Hip strategy** (secondary, engages only once the ankle correction
   saturates against its bound): an additional PD term contributing a hip
   roll/pitch offset for larger disturbances the ankles alone can't recover.

**Safety bounds on the correction itself** — this matters because the
balance loop bypasses the laptop-side safety checks entirely (next section),
so it has to carry its own:
- Every corrective output is clamped through the same `JOINT_LIMITS` bounds
  used everywhere else (`validation.py`) before being written to the servo
  bus — the balance loop must never be able to command a joint out of range.
- A max correction magnitude and a max rate-of-change, so a bad gain or a
  sensor glitch can't produce a sudden large joint jump.
- A small deadband around zero tilt, so the robot doesn't constantly
  micro-jitter (and wear the servos) while standing still and level.

**Milestone order:** get two-leg standing balance solid first — that's what
the mimicry use case actually needs, since the robot is on two feet for the
overwhelming majority of what a child would ask it to mirror. Single-leg
standing is a much harder version of the same problem (support area shrinks
to roughly one foot's ~4×2.5 cm pad, versus two), and should come after,
once the two-leg controller and tuning process are proven out.

## 5. Why per-body-part mass isn't needed, but per-pose CoM is

This was asked earlier in the conversation and is worth stating precisely
in the plan: a single whole-body mass + one static-pose CoM number would
**not** be enough, because CoM has to be predictable at every pose the
retargeting pipeline can produce (weight shifted, arm raised, torso tilted),
not just at `stand`. That prediction, though, doesn't require you to measure
every link by hand — MuJoCo already computes whole-body CoM at *any* pose
automatically via forward kinematics over the per-link mass/CoM values
already in `ainex.xml`, and those values already match the manufacturer's
CAD data (§2). The one correction actually missing is the lumped
battery/wiring mass (§1.1–1.2). Full per-link rotational inertia tensors are
lower priority — point-mass-at-CoM is the standard simplification for
CoM-over-support-polygon balance strategies (used in classic
inverted-pendulum/ZMP controllers) and is good enough for ankle/hip
strategy control; it only matters more if you later move to precise torque
control.

## 6. Telling the child when a pose isn't possible

**This partially exists today, but not on the mimicry path.** There's
already a safety-verdict mechanism
(`fall_blocked` / `collision_clamped` / `safe_fraction` /  `bad_pairs`,
defined in
[`collision_checked_targets()`](../backend/app/services/motion.py)) that
flows back through `/move` and chat-driven waypoint execution, and is
surfaced to the child for pose capture and spoken fine-tuning adjustments.

Tracing the live mimicry path specifically:

- **Joint-range limits** *are* enforced during live follow —
  `pose_to_robot.py` clamps every joint to `JOINT_LIMITS` — but silently:
  the clamped value is used with no signal that clamping happened.
- **Self-collision and fall/stability checks are not applied at all**
  during live follow. `FollowController` is constructed
  (`backend/app/main.py`) with `dispatch_fn = dispatch_servo_commands` —
  the raw send chokepoint — not `execute_waypoints`, which is the only
  thing that actually calls `collision_checked_targets()`. So today, a pose
  a child strikes that would self-collide or tip the robot over goes
  straight to the servos with no check and no feedback at all.

To meet "if the child does something the robot can't physically do, tell
them," the follow path needs to route through the same
`collision_checked_targets()` check the other dispatch paths already use
(clamped, not necessarily blocked — a fall-blocked verdict during
continuous mimicry should probably hold the last safe pose rather than
freeze mid-motion, but that's a UX call to make during implementation), and
the joint-range clamp in `pose_to_robot.py` needs to report *that* it
clamped, not just silently return the clamped value.

**A second design decision worth flagging now, not after building it:**
a spoken response on *every frame* the child holds an unreachable pose would
be constant chatter (retargeting runs continuously, many times a second).
This needs debouncing — e.g., speak once when a sustained infeasibility
starts, not per-frame, and once when it clears — rather than being wired
straight to the per-frame safety verdict.

## 7. What needs to be tuned by hand, and how

| What | Why it can't be computed | How to tune it |
|---|---|---|
| **Mass/CoM correction** (§1) | CAD data omits battery/wiring | One-time: scale + measured offset, cross-checked with the two-scale stand measurement. Not iterative. |
| **Ankle PD gains (Kp, Kd)** | Sim actuator response (generic MuJoCo PD, `kp=50/kv=5`) isn't calibrated to the real bus servo's actual response — this doesn't transfer 1:1 from sim | Get gains into the right ballpark in sim first (cheap, safe — also catches sign errors: wrong joint moving the wrong way). Then on hardware: start low, raise `Kp` while gently pushing the standing robot by hand until you see sustained oscillation ("shivering"/increasing wobble), back off to roughly half that value, then raise `Kd` until the remaining oscillation damps out. Standard manual PID-by-feel procedure — no special equipment needed, just repeated pushes and watching/feeling the response. |
| **Hip PD gains** | Same reason, plus they only ever engage once ankle saturates, so they can't be tuned until ankle gains are already reasonable | Same procedure as ankle, but test with pushes large enough to saturate the ankle correction (so the hip term actually engages) rather than small taps. |
| **IMU filter cutoff** (low-pass or complementary filter on raw gyro/accel) | Real sensor noise isn't present in sim at all | Log/print raw IMU values with the robot stationary vs. being moved by hand; pick the lowest cutoff that visibly removes stationary noise without adding perceptible lag to the correction (watch for the robot feeling "sluggish" to catch a push — that's the cutoff set too aggressively). |
| **Deadband** (how much tilt to ignore) | Trade-off between servo wear and responsiveness, not a physical constant | Too small → visible/audible micro-jitter while standing still (back it off). Too large → doesn't correct small real tilts (bring it back down). Tune by watching/listening to the robot standing idle. |
| **Correction saturation limits** (max joint offset, max rate) | Safety bound with no single correct value — depends on how much you trust the current gains | Start conservative (small clamp) while gains are still being found; raise only as confidence grows. This is a safety knob, tune it last and cautiously. |
| **Joint-limit safety margin for spoken feedback** (§6) | Judgment call about how close to the true mechanical limit to get before telling the child, vs. just silently doing the closest reachable pose | Watch how it looks/feels in testing — e.g., trigger the spoken response at ~90% of a joint's range rather than exactly at the hard limit, adjust based on whether it feels like it's speaking up too early or too late. |
| **Balance loop rate** | Bounded by real Pi CPU headroom (shared with the always-on vision process) and the servo bus, not a number to assume | Measure the actual read-IMU → compute → write-servo cycle time on the Pi once code exists; 50 Hz (the servo bus's own control cycle) is the realistic ceiling, not a target to exceed. |

## 8. Suggested rollout order

1. Wire `get_imu()` through the Pi agent so IMU data is actually reachable
   from a background process (software only — no tuning yet).
2. Correct the sim's mass model for the missing battery/wiring mass (§1).
3. Build the two-tier (ankle → hip) controller and get gains into a
   reasonable range in sim.
4. Move to hardware: tune gains with the robot just standing still, no
   mimicry involved yet — "stands and resists a push" as the bar to clear.
5. Integrate with live mimicry: balance loop running as the always-on
   background correction under whatever pose `follow`/`/move` is currently
   commanding.
6. Route the follow path through `collision_checked_targets()` and add
   debounced spoken feedback for clamped/blocked poses (§6).
7. Only once two-leg balance is solid end-to-end: attempt single-leg
   stance.

## 9. Open risks worth tracking

- No foot-contact sensing on real hardware — if IMU-only turns out to be
  insufficient for reliable balance (plausible, especially for single-leg),
  the fallback is inferring support state from which foot's joints are
  bearing load (servo current/torque, if the bus servos expose it) rather
  than adding hardware.
- Balance-loop-vs-mimicry ownership (§3) is a real design decision, not a
  detail — get it wrong and the two fight each other.
- Pi CPU budget shared with vision hasn't been measured; the balance loop's
  achievable rate is unknown until it's built and profiled on-device.
