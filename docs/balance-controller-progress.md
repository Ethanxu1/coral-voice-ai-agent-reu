# Balance Controller — Progress

Tracks implementation against the plan in
[`balance-controller.md`](balance-controller.md). Update this file
whenever a checklist item's status actually changes — keep it accurate,
not aspirational.

**Status legend:** ✅ done · 🚧 in progress · ⛔ blocked (on what) · ⬜ not started

---

## Phase 0 — Controller core (software only, sim/hardware-agnostic)

| | Item |
|---|---|
| ✅ | Two-tier ankle/hip PD controller (`backend/app/balance/controller.py`) — pure function of attitude + rate in, joint offset out, no MuJoCo/hardware dependency |
| ✅ | Safety bounds implemented: hard per-channel magnitude cap, rate-of-change cap, deadband |
| ✅ | `apply_balance_offset()` — adds a correction to a baseline pose and clamps through the real `JOINT_LIMITS` table (the same one every other dispatch path uses) |
| ✅ | Unit tests (`backend/tests/test_balance_controller.py`, 20 tests) — deadband, ankle-only vs. ankle+hip engagement, correct-sign check, both safety caps, rate-limit convergence, `reset()`, joint-limit clamping |
| ⛔ | **Gain values are placeholders, not tuned** — blocked on Phase 1 (sim integration) to actually iterate on them |
| ⛔ | **Attitude sign convention (`AttitudeReading`'s pitch/roll meaning) is a documented assumption, not verified** — blocked on Phase 1 producing a real MuJoCo-sourced reading to check against |

## Phase 1 — Sim integration

| | Item |
|---|---|
| ✅ | Sensor adapter (`backend/app/balance/sim_source.py`, `read_attitude()`) — reads the model's `upvector`/`global_angvel` sensors (world-frame; simpler and more robust than decomposing `body_quat`, which turns out to carry a nontrivial baked-in offset even at `stand` — see the module docstring) |
| ✅ | Sign convention **empirically verified for the sensor reading itself** — 6 tests (`backend/tests/test_balance_sim_source.py`) rotate the model a known amount and check the reading matches, not just "changed." Found and fixed a real bug this way: pitch and roll do **not** share the same formula — roll needs a negation pitch doesn't (`roll_rad = atan2(-uy, uz)` vs `pitch_rad = atan2(ux, uz)`). Would have shipped backwards without this check. |
| ✅ | Wired into the live sim (`backend/app/balance/sim_loop.py`, `SimBalanceLoop`) — off by default, `POST /balance/start`/`stop`/`push`, `GET /balance/status`. Watchable live in the browser viewer (`/ws/sim`). |
| ✅ | **Closed-loop verification: the correction direction is confirmed correct**, 2026-09-14. See "What Phase 1 actually found" below — resolves the question the 2026-09-09 headless attempt left open. |
| 🚧 | **Gains partially tuned, then paused deliberately** — `max_rate_rad_per_s` raised 2.0 -> 3.0, cutting peak post-push overshoot roughly in half (-1.96° -> -0.93°) with no instability; this was the actual bottleneck, not `ankle_kd`. The remaining ~0.3° steady-state residual resisted both `ankle_kp` and `deadband_rad` changes — needs a real integral term to fully close, not a number tweak; not chased further since 0.3° is far below any stability concern. See "What Phase 1 actually found" below for the full account. |
| ✅ | **Hip engagement confirmed, 2026-09-15** — swept push strength 6-9 rad/s reading `/joint_states` directly (not just eyeballing the viewer). See "What Phase 1 actually found" below for the full sweep and the narrow recoverable-vs-fall window it revealed. |
| — | **Not visible on the 3D model at current gains — confirmed a real limitation, not a bug.** Swept push strength 0.3-12 rad/s: below ~9 rad/s the corrected-vs-uncorrected difference stays a few tenths of a degree (real, per the numbers above, but invisible by eye); above ~9 rad/s the robot falls over (~90°) **regardless of correction** — the safety caps (`max_correction_rad`≈11°) intentionally keep any single correction small, so they can't arrest a disturbance that large by design, not by bug. `GET /balance/attitude` added so this can be checked by number instead of by eye until gains are tuned enough to be visible. |

### What Phase 1 actually found

**2026-09-09 attempt (headless, inconclusive):** closed-loop physics
test with placeholder gains looked like it made things worse; further
single-joint probes produced messy, hard-to-interpret coupled results.
Left as an open question — see the session log for that day if curious
about the dead end itself.

**2026-09-14 (resolved):** re-ran the same kind of test, correctly this
time — push the live simulator via the new `/balance/push` endpoint,
compare final settled roll with the loop off vs. on, using
`read_attitude()` (real attitude) rather than `/joint_states` (which
reads commanded ctrl *targets*, not the free base's actual lean — this
was the first mistake caught while building this comparison; it will
look identical with the loop off or on because a push never touches an
actuator's target directly, only the controller does). Reproduced at two
push strengths:

```
                    no correction    with correction
1.0 rad/s push  ->  settles +0.55°   settles -0.22° to -0.35°
0.3 rad/s push  ->  settles +0.53°   settles -0.28° to -0.30°
```

Consistent, reproducible ~45-47% reduction in final resting tilt
magnitude at both strengths — **the correction direction is correct.**
Both trials also show the correction overshooting through level to the
opposite side before settling (visible in the traces, e.g. the 1.0 rad/s
trial dips to -0.98° before recovering to -0.22°) — classic underdamped
PD behavior, not a sign error. This is exactly the "sim gains don't
transfer 1:1, get them in the right ballpark, then iterate" situation
the plan already expected (§7), now with a concrete, specific fix
(more `ankle_kd`, or less `ankle_kp`) rather than an open question.

**2026-09-15: gain tuning attempt, and a live A/B methodology fix.**
User's own `/balance/push` + `/balance/attitude` test at first looked
contradictory (loop-on landed *further* from the robot's natural resting
lean than loop-off) — traced to two methodology gaps, not a real
regression: (1) trial 2 wasn't reset before running, so it inherited
trial 1's ending tilt/momentum instead of a clean start (fixed by
calling `POST /reset` before each trial — same endpoint the UI's
"Reset to stand" button already uses, confirmed via `frontend/src/demo/api.ts`'s
`resetPose()`); (2) the resting baseline itself is ~0.52-0.53° off true
level, not 0° — the known right-heavy mass asymmetry, not sensor noise.

With both controlled for, the numbers match the 2026-09-09 headless
finding: uncorrected resting lean 0.52-0.53°, corrected settles at
-0.27° to -0.36° (fine-grained sampling, 0.1s steps) — about a 45%
reduction in |tilt| from true level, reproduced live in the browser sim
this time, not just a standalone script. The controller doesn't fully
zero out because it's pure PD with no integral term fighting a
*constant* bias torque (gravity on the asymmetric mass) — some steady-state
error is mathematically expected, not a bug.

Fine-grained trace (0.1s steps, 3.0 rad/s push, `kd=0.08`) for the
actual overshoot shape:

```
t=0.1s  +1.59°   (push still winning)
t=0.2s  -1.20°   (crossed level)
t=0.3s  -1.96°   (peak overshoot)
t=0.4s  -1.47°
t=0.5s  -0.86°
t=0.7s  -0.28°   (essentially settled)
t=1.5s  -0.34°   (steady state, holds flat)
```

Tried raising `ankle_kd` to damp that peak: `0.05 -> 0.15` (3x) caused
sustained, large oscillation (roll swinging roughly -10° to +3°, pitch
swinging with it) — a real instability, not just more overshoot. Backed
off to `0.05 -> 0.08` (1.6x): stable, but the fine-grained trace above
shows it's nearly identical to what `kd=0.05` produces at the same
timestamps — no measurable benefit. Working theory: the response in this
range is dominated by `max_rate_rad_per_s` (2.0 rad/s, ~0.04 rad/tick)
and `ankle_saturation_rad` (0.12 rad) capping what actually reaches the
joint, not by `kd` itself — so small `kd` changes do little until a
large enough change (3x) pushes the loop into a different, unstable
regime, likely via the hip channel's independent, unrated PD term
engaging once ankle saturates. Reverted to the original 0.05/0.6
defaults (no proven benefit to keeping 0.08) — **next real levers to try
are `max_rate_rad_per_s` (loosen, so correction can act faster without
touching kd/kp) or `ankle_kp` (to address the steady-state residual
directly), not further blind `ankle_kd` increases.**

**2026-09-15 (continued): `max_rate_rad_per_s` confirmed as the real
lever, tuned to 3.0.** Tested the working theory directly — same
fine-grained push-response trace, `ankle_kd`/`ankle_kp` back at their
original 0.05/0.6, only `max_rate_rad_per_s` changed:

```
max_rate_rad_per_s = 2.0 (original)  ->  peak overshoot -1.96° (t=0.3s), settled by ~t=0.7s
max_rate_rad_per_s = 3.0             ->  peak overshoot -0.93° (t=0.3s), settled by ~t=0.5s
max_rate_rad_per_s = 4.0             ->  peak overshoot -1.10° (t=0.3s), settled by ~t=0.6-0.7s
```

3.0 is a clear local improvement over 2.0 (peak roughly halved, faster
settle, no instability at any of the three values tested); 4.0 is
slightly worse than 3.0, not better — diminishing/reversing returns
right where expected. Kept `max_rate_rad_per_s = 3.0` as the new default
in `BalanceGains` (comment in the source records the three data points).
Steady-state residual (~-0.3°) is unchanged across all three, as
expected — this parameter only affects how fast the correction can
move, not where it settles.

**2026-09-15 (continued, again): steady-state residual resists both
`ankle_kp` and `deadband_rad` — needs an integral term, not a number
tweak.** Two more attempts at shrinking the ~-0.3° residual, both with
`max_rate_rad_per_s` staying at 3.0:

```
ankle_kp   0.6 -> 0.8   (33% up)     -> settled ~-0.28° (was ~-0.30°) -- no real change, overshoot slightly worse (-1.05° vs -0.93°)
deadband_rad 0.01 -> 0.003 (10x down) -> settled ~-0.32° (was ~-0.30°) -- no real change either
```

Initial theory (mid-session) was that `deadband_rad` — 0.01 rad ≈ 0.57°,
larger than the observed residual — was gating the position-error term
to zero once "close enough," which would explain why `ankle_kp` alone
did nothing. Directly tested by shrinking the deadband to 0.003 rad
(≈0.17°, smaller than the residual, so it should no longer gate
anything) — **the residual didn't move.** That disproves the deadband
theory; both attempts reverted, code is back to exactly its last
committed state plus the kept `max_rate_rad_per_s` change.

**Conclusion:** this residual isn't a one-line tuning fix — it needs a
genuinely different kind of term (integral: accumulate error over time,
push harder the longer a constant bias persists) that the current
`BalanceGains`/`BalanceController` shape doesn't have, not a bigger
value for anything that exists today. Given the residual is ~0.3° —
far below any stability concern, the robot doesn't even begin to fall
until push strengths an order of magnitude larger (see the push-strength
sweep above) — **decided not to chase this further in this round.**
Adding an integral term is real new scope (needs anti-windup design so
it can't overcorrect from a long-held disturbance) for if/when it's
actually needed, not a default next step.

**2026-09-15 (continued, final): hip channel engagement confirmed, and
the recoverable window turns out to be narrow.** Swept push strength
6.0-9.0 rad/s, reading `/joint_states` directly for `l_hip_roll`/
`l_ank_roll` (not just watching the viewer) alongside `/balance/attitude`:

```
6.0 rad/s -> ankle peaks 0.039 rad (well under the 0.12 cap) -> hip never engages -> recovers easily
7.0 rad/s -> ankle peaks 0.086 rad (still under cap)          -> hip never engages -> recovers
8.0 rad/s -> ankle peaks 0.118 rad (just under cap)           -> hip never engages -> recovers
8.3 rad/s -> ankle saturates briefly                          -> hip engages briefly (-0.08 rad) -> recovers, settles near level
8.6 rad/s -> ankle saturates continuously                     -> hip creeps upward, doesn't cap out -> doesn't recover, but doesn't fall fast either -- slow, marginal drift
9.0 rad/s -> ankle saturates instantly                        -> hip engages, maxes out at -0.2 rad -> falls anyway (roll climbing past 39° and still rising)
```

**Hip engagement is real and works as designed** — at 8.3 rad/s it
visibly takes over once the ankle alone would have exceeded its soft
bound, and the robot still recovers. But the window where hip
engagement actually *helps* (rather than just delaying an already-lost
fall) is narrow — roughly 8.0-8.3 rad/s out of the whole tested range.
By 8.6 rad/s the robot is in a slow, marginal drift even with hip
engaged, and by 9.0 rad/s both channels are maxed out and it falls
anyway. This is consistent with, and now gives a concrete number to,
the earlier push-strength-sweep finding ("above ~9 rad/s the robot
falls regardless of correction, by design — the safety caps intentionally
keep any single correction small"). Not treated as a bug: the caps
exist specifically so a bad gain or sensor glitch can't command
something dangerous, and a wider recoverable margin would need larger
`max_correction_rad`/`ankle_saturation_rad` — a real hardware-safety
tradeoff to make deliberately later, not a default to widen now.

## Phase 2 — Hardware prerequisites (physical, yours — not blocked on code)

| | Item |
|---|---|
| ✅ | Weigh the robot — **2.471 kg** total (single scale); independently cross-checked by the two-scale split summing to 2.479 kg (8 g apart, good agreement) |
| ✅ | Two-scale standing balance check — **right 1.348 kg / left 1.131 kg** at stand, a real 217 g lateral imbalance (agrees with the total above, so not measurement noise) |
| ✅ | Corrected `body_link`'s mass in `assets/ainex/ainex.xml` for the missing 123.5 g, offset ~52 mm toward the robot's right (solved via moment balance against the two-scale split and the model's own stand-pose foot separation, not eyeballed) — model's total mass now matches the scale exactly (2.471 kg); derivation in `.agents/logs/2026-09-13-body-link-mass-correction.md`. Visual cross-check: user confirmed the right side does visibly have more wiring/motherboard mass than the left — direction and rough magnitude both plausible, not just a number that happens to fit |
| ✅ | Confirmed the onboard IMU responds — `ainex_sdk`'s `imu_demo.py` (`Board().get_imu()`), visibly tracked tilting by hand, and returns **9 floats**: accel (g, magnitude ≈1.009 at rest — sanity-checks as correct), gyro (deg/s, nonzero at rest = normal bias, not motion), magnetometer (µT-scale, magnitude ≈75, plausibly distorted by nearby electronics as usual). 9, not 6 — a heading estimate is available later, not just tilt. |

## Phase 3 — Hardware integration

| | Item |
|---|---|
| ✅ | Raw IMU access on the Pi — `GET /imu` added to `backend/app/robot/pi/nodes/server.py`, returns `Board().get_imu()`'s floats unmodified. IMU init failure doesn't take down `/move`/`/health` (wrapped, logs a warning, route reports 503 instead). **Not yet deployed or tested on the real Pi** — needs the usual scp/docker cp/chmod cycle. **Not yet checked for serial contention with `/move`** — unknown whether reading IMU while a body command is in flight causes any conflict; test both together before trusting it under load. |
| ✅ | `ComplementaryFilter` (`backend/app/balance/complementary_filter.py`) — fuses raw accel+gyro into an `AttitudeReading`, same output shape `sim_source.py` produces, so `BalanceController` doesn't care which one fed it. 12 unit tests (8 synthetic + 4 locking in real hardware readings below). |
| ✅ | Deployed `/imu` to the Pi and confirmed it responds — `[server] IMU board ready`, doesn't affect `/move`. |
| ✅ | **Roll AND pitch axis convention CONFIRMED against real hardware, 2026-09-17 — corrects the 2026-09-14 entry below, which had them swapped.** `accel_roll = atan2(ax, ay)`, `accel_pitch = atan2(az, ay)`. Confirmed with two clean, mechanically-constrained tests (not freehand tilts): lifting one foot so weight shifts onto the other leg swung `ax` hard while `az` stayed at baseline; tipping the robot forward swung `az` hard while `ax` stayed at baseline. See "Verifying the real IMU's axis convention" below for the full account, including why the original test was wrong. |
| ✅ | `BalanceLoop` (`backend/app/robot/pi/nodes/balance_loop.py`) — background thread wiring `BalanceController` to the real IMU and the body service, **roll channels only** (pitch discarded every tick — now that pitch's axis is also confirmed, this is a scope choice to revisit, not a safety gate on unverified data; see above). Off by default; `POST /balance/start`/`stop` + `GET /balance/status` added to `server.py`. Deploy chain and end-to-end tick logic verified by simulation (fake board + real recorded IMU readings, run outside any Pi) — confirmed the correction converges smoothly and the two-tier ankle→hip handoff engages correctly. **Not yet deployed to the Pi or run against real servos.** |
| ✅ | **Single-shot sign check CONFIRMED on real hardware, 2026-09-21.** `scripts/balance_sign_check.py` (before/after IMU reading around one real `/move` correction) run twice, both directions: left-foot-lift lean (+5.28° → +3.96°) and right-foot-lift lean (-7.63° → -7.53°) — both moved `|roll|` toward level. Uses the corrected `atan2(ax, ay)` formula through the real production `/move` pipeline, not a mock. See "Hardware sign check" below for the full account, including two false-alarm "wrong direction" results traced to a test-procedure timing issue (not a code bug) before this. |
| ⬜ | Tune gains by feel on hardware: robot standing still, no mimicry — "stands and resists a push" is the bar (plan §7's push-test procedure) |
| ⬜ | **Crash mat / soft test area in place before this phase starts** — early gain tuning on real hardware means falls are expected |

### Verifying the real IMU's axis convention

**2026-09-14 attempt (WRONG — corrected below, kept here so the mistake
stays visible instead of quietly vanishing).** Real data, robot actively
torque-holding `stand`:

```
standing: ( -0.023, 0.997, 0.054 )  -> "roll" = atan2(0.054, 0.997) ≈ 3°
right:    ( -0.024, 0.151, 0.981 )  -> "roll" = atan2(0.981, 0.151) ≈ 81°
```

This looked like solid confirmation of `accel_roll = atan2(az, ay)` at
the time — standing near-level, a large jump under tilt, in the expected
direction. Pitch (`atan2(ax, ay)`) then failed 5 separate attempts that
same day, the clearest of which (a real, unambiguous toe-pivot forward
lean) came out reading as 97° of *roll* instead of pitch — `ax` stayed
near zero throughout, `ay`/`az` moved the way the "roll" formula
responds to. Deferred pitch rather than force a conclusion; working
theory at the time was that the robot's own mass asymmetry was coupling
sideways rotation into forward tilts applied by hand.

**2026-09-17 correction: roll and pitch were swapped the whole time.**
While debugging why a live sign-check test kept showing no response to
deliberate sideways tilts, the same pattern kept appearing: `ax` swinging
large, `az` staying near baseline — repeatedly, across freehand attempts
at a sideways lean. That's backwards from what `accel_roll = atan2(az,
ay)` predicts. Rather than assume the freehand tilts were somehow all
still wrong, switched to two *mechanically constrained* motions (harder
to accidentally apply along the wrong axis than free-handing a torso
tilt):

```
foot lifted, weight shifts to the other leg (should be pure sideways/roll):
    accel = (0.811, 0.522, 0.027)  -- ax swings hard, az stays at baseline

robot tipped forward onto its toes (should be pure forward/pitch):
    accel = (-0.001, 0.844, 0.530) -- az swings hard, ax stays at baseline
```

Two independent, mutually-exclusive axis responses — about as clean as
real hardware data gets. This means `ax` is the roll-responsive axis and
`az` is the pitch-responsive one, the **opposite** of the 2026-09-14
"confirmation." And it explains that day's data in hindsight: the
"right tilt" reading above (`accel=(-0.024, 0.151, 0.981)`) has `az`
swinging to 0.98 while `ax` stays near zero — the *exact* signature
2026-09-17's dedicated forward-lean test produced independently. The
2026-09-14 test was very likely a forward/pitch-type tilt that got
mislabeled as "tilt toward its own right." It also resolves the old
pitch mystery: that day's "97° of roll" forward-lean result was correct
all along, just read through a formula with the wrong name on it — it
really was pitch.

**Corrected formulas** (`backend/app/balance/complementary_filter.py`):

```
accel_roll  = atan2(ax, ay)   -- CONFIRMED 2026-09-17
accel_pitch = atan2(az, ay)   -- CONFIRMED 2026-09-17 (same evidence — see above)
```

**Still open:** `roll_rate`/`pitch_rate` (from the gyro's `gx`/`gy`) were
NOT touched by this fix — that pairing is a separate, still-unverified
assumption. Confirming it needs a controlled constant-rate rotation, not
a held static tilt (all a test like the ones above can produce by hand)
— a harder test, not yet attempted. Don't assume it's right just because
the accel formula was fixed.

**Lesson for future by-hand hardware tests on this robot:** freehand
tilting (gripping the torso and rotating it by feel) is not reliable
enough to trust for axis-convention work, even when the tester is
confident about the direction applied — it produced consistent,
repeatable *wrong-axis* readings across multiple attempts. A
mechanically constrained motion (foot lifted, weight shifted onto a
single support point) is what actually resolved it. Prefer that pattern
over "hold it and tilt" for any future real-hardware calibration.

### Hardware sign check

**Confirmed 2026-09-21, both directions, real hardware.** Once the axis
fix above landed, `scripts/balance_sign_check.py` was rewritten to read
the IMU both before *and* after sending one real correction (same
sustained lean held throughout, ~1s apart) — a numeric before/after
instead of asking a human to judge "did it push back" by feel, which
turned out not to work (see below).

```
left-foot-lift lean (weight on right leg):  +5.28° -> +3.96°  (-1.31°, toward level)
right-foot-lift lean (weight on left leg):  -7.63° -> -7.53°  (-0.09°, toward level)
```

Both directions moved `|roll|` toward level. This is the real answer to
the question the whole Phase 1/3 effort has been chasing — not a sim
number, not a mocked dispatch, the actual production `/move` pipeline
driving real servos from a real IMU reading.

**Two false starts on the way, both test-procedure issues, not code
bugs — worth recording so they don't get mistaken for a real problem
next time:**

1. **"Feel" isn't diagnostic.** The first physical impression (holding
   the robot in a lean, feeling it "want to return to normal standing")
   turned out to be the robot's own pre-existing stand-pose holding
   torque — a much bigger effect than our few-degree correction, and
   present whether or not the correction is even running. Same lesson
   the sim testing already learned about vision (too subtle to see by
   eye) — this is the hand-feel equivalent. Fixed by reading the IMU
   numerically before/after instead of judging by touch.
2. **A "before" reading taken while the lean is still developing (not
   yet held steady) produces a false "wrong direction" result.** Two
   consecutive attempts showed `|roll|` apparently increasing sharply
   right after the correction — but in both cases the computed
   correction was tiny (a fraction of a degree, since the "before" roll
   was itself small/near the deadband), far too small to explain the
   several-degree swing observed. The real cause: the tester was still
   settling into the held lean when "holding now" was said, so the
   "after" reading (~1s later) mostly captured their own continuing
   motion, not the correction's effect. One test also started measuring
   from a leftover, un-settled state from the *previous* test because
   the robot wasn't reset (or the tester hadn't released) in between.
   Fixed by explicitly holding the lean fully still for a couple of
   seconds *before* saying "holding now," not while transitioning into
   it.

**Lesson for future hardware tests:** a clean before/after comparison
needs the disturbance to be genuinely constant across both reads, not
just "the same general motion" — get into position, let it settle,
*then* start the measurement, same discipline the sim A/B testing on
2026-09-15 already learned about resetting between trials.

### Deploying the balance loop

`balance_loop.py` needs four sibling files deployed alongside it and
`server.py` in `~/ros_ws/src/ainex_demo/nodes/` on the Pi (same scp →
`docker cp` → `chmod +x` cycle as always, just more files this time):
`controller.py` and `complementary_filter.py` (from `backend/app/balance/`),
`hardware_angle_utils.py` and `servo_config.py` (from `backend/app/robot/`).
Each has a try/except import fallback specifically so the same file works
both as part of the Mac's `app` package (tested) and as a flat sibling
file on the Pi — don't remove those fallbacks thinking they're dead code.

Real, load-bearing constraint found while building this, not a target:
the loop's achievable rate is capped well below the servo bus's 50 Hz
ceiling — `body.py`'s blocking service sleeps ≥0.1s per call regardless
of requested duration, so realistically ≤10 Hz. The control math is
unaffected (every tick uses its own measured `dt`, never an assumed
fixed rate), but this is worth knowing before expecting a snappy
correction.

## Phase 4 — Mimicry integration

| | Item |
|---|---|
| ⬜ | Balance loop runs as the always-on correction under whatever pose `follow`/`/move` is currently commanding |
| ⬜ | Route the live-follow path through `collision_checked_targets()` (currently skipped entirely during follow — see plan §6) |
| ⬜ | Debounced spoken feedback when a requested pose is out of reach (speak once when infeasibility starts, once when it clears — not per-frame) |

## Phase 5 — Single-leg (only after two-leg is solid end-to-end)

| | Item |
|---|---|
| ⬜ | Not started — explicitly sequenced last; support area shrinks to ~one foot's pad, meaningfully harder than two-leg |

---

## Open questions / risks (carried from the plan, unresolved)

- No foot-contact sensing on real hardware — if IMU-only proves insufficient (most likely for single-leg), the fallback is inferring support state from per-foot servo load, not new hardware.
- Pi CPU budget shared with the always-on vision process — the balance loop's achievable rate is unmeasured until it's actually running on-device.
- Balance-loop-vs-mimicry ownership (bounded offset added on top, never replacing retargeting's output) is a real design decision already made in the Phase 0 code — don't let a later change quietly turn it into two systems fighting over the same joints.

## Log

- **2026-09-09** — Phase 0 done: `backend/app/balance/controller.py` + 20 passing unit tests. Nothing wired into the live sim or hardware yet — this phase was deliberately scoped to be provable without either. Next: Phase 1 (sim sensor wiring).
- **2026-09-09 (same day, continued)** — Phase 1 sensor adapter done and verified (`sim_source.py`, 6 tests, one real sign bug found and fixed). Attempted closed-loop verification that the controller's correction actually helps; inconclusive — see "What Phase 1 actually found" above. Not wired into the live `AiNexSimulator` loop pending that. Next: re-attempt with the sim viewer open for visual feedback, or iterate on gains/coupling with a human watching.
- **2026-09-13 (continued)** — Phase 3 started, software-only per the plan's own sequencing (nothing drives real servos yet): `GET /imu` added to the Pi server (raw passthrough, doesn't take down `/move` if IMU init fails), `ComplementaryFilter` built and tested (8 tests, synthetic data). Not yet deployed to the Pi or checked against real hardware — the axis convention is an assumption ported from sim, unverified; see "Verifying the real IMU's axis convention" above. Next: deploy, run that check, then the background loop + gain tuning.
- **2026-09-15** — User tried the live demo, correctly reported no visible difference between loop on/off on the 3D model. Investigated rather than assumed: swept push strength 0.3-12 rad/s — the real difference stays a few tenths of a degree below ~9 rad/s (matches the earlier finding, just genuinely too subtle to see by eye), and above ~9 rad/s the robot falls over regardless of correction, since the safety caps intentionally keep any single correction small. Not a bug; confirms gains need tuning to be visually assertive, which was already the known next step. Added `GET /balance/attitude` so this can be checked numerically instead of by eye in the meantime.
- **2026-09-14 (continued, again)** — Wired the loop into the LIVE sim too (`sim_loop.py`, `/balance/start`/`stop`/`push`/`status`), watchable in the browser viewer. Used it to finally resolve Phase 1's open question: pushed the sim with the loop off vs. on at two strengths, compared settled roll via the correct signal (`read_attitude()`, not `/joint_states` — first attempt measured the wrong thing). Correction direction confirmed correct, reproducibly (~45-47% reduction in settled tilt both times) — response overshoots before settling, so gains (more damping, less proportional gain) are next, not a sign fix. See "What Phase 1 actually found" above.
- **2026-09-14 (continued)** — Built `BalanceLoop` (roll only, off by default) and wired `POST /balance/start`/`stop`, `GET /balance/status` into the Pi server. Verified the whole deploy-time import chain and a full simulated tick sequence (real recorded IMU readings, fake dispatch) outside any Pi — correction converges smoothly, ankle→hip handoff engages correctly. Found the loop's real achievable rate is capped around 10 Hz by `body.py`'s own blocking design, well under the 50 Hz ceiling. Not deployed to real hardware yet — next is the single-shot sign check (does the correction actually help), before ever turning the loop on continuously.
- **2026-09-14** — Deployed `/imu` to the Pi, confirmed it works. Roll axis convention confirmed against real hardware after several failed attempts (robot unpowered, then "resting on a table" protocol, both gave uncontrolled/inconsistent baselines) — with the robot actively torque-holding `stand`, real tilt data confirmed `accel_roll = atan2(az, ay)`, 3 independent trials agreeing (the original formula's axis *pairing* was wrong, not just its sign — real "up" is Y, not Z). Pitch: 5 attempts, all inconclusive or contradictory — the clearest one (a real, confirmed toe-pivot forward lean) read as 97° of *roll*, not pitch. Deliberately deferred rather than guessed at — see "Verifying the real IMU's axis convention" for the full account and working theory (the robot's own right-heavy mass asymmetry may make pitch impossible to isolate from a by-hand test). `complementary_filter.py` and tests updated to the confirmed roll formula; pitch stays an explicitly-flagged unverified placeholder.
- **2026-09-13** — Phase 2 done, all four items: weighed the physical robot (2.471 kg), two-scale stand-pose split (right 1.348 kg / left 1.131 kg, a real 217 g imbalance, visually confirmed against the robot's actual wiring/motherboard layout), corrected `body_link`'s mass in `ainex.xml` by moment balance (not eyeballed) to match, and confirmed the onboard IMU responds — `ainex_sdk`'s `imu_demo.py` returns 9 floats (accel/gyro/magnetometer), accel magnitude ≈1g at rest sanity-checked the reading. Next: Phase 3 (hardware integration) — wire `get_imu()` through a Pi-side HTTP route, run the balance loop as its own always-on process there, tune gains by feel with the robot standing still.
- **2026-09-15 (continued)** — Live sim A/B testing with the user via curl, iterated on methodology twice: first pass wasn't reset between trials (fixed with `POST /reset`, confirmed equivalent to the UI's own "Reset to stand" button), second pass revealed the resting baseline isn't 0° (~0.52-0.53°, the known mass asymmetry) so raw absolute readings needed comparing as deltas, not face value. Clean result reproduces the 2026-09-09 finding live (~45% reduction in |tilt| from level). Attempted a first gain-tuning pass on `ankle_kd`: found a narrow, non-linear margin — 1.6x was statistically indistinguishable from baseline, 3x caused real oscillatory instability (not just more overshoot). Reverted to original gains; no net code change. Full trace and reasoning in "What Phase 1 actually found" above.
- **2026-09-15 (continued, again)** — Tested the working theory from the `ankle_kd` dead end directly: swept `max_rate_rad_per_s` (2.0 -> 3.0 -> 4.0) with `ankle_kd`/`ankle_kp` back at defaults. Confirmed it — 3.0 cut peak post-push overshoot roughly in half (-1.96° -> -0.93°) with no instability; 4.0 was slightly worse than 3.0 (diminishing returns, as expected once a parameter's helpful range is found). Kept `max_rate_rad_per_s = 3.0` as the new default — first real, kept gain change from this tuning round.
- **2026-09-15 (continued, once more)** — Two more attempts at the ~-0.3° steady-state residual: `ankle_kp` 0.6 -> 0.8 (no real change, overshoot slightly worse) and `deadband_rad` 0.01 -> 0.003, a direct test of the theory that the deadband was gating the residual to a stop (disproved — residual unchanged even with a much smaller deadband). Both reverted; concluded this residual needs a real integral term, not a number tweak, and isn't worth chasing further right now given it's ~0.3° — nowhere near a stability concern. Full account in "What Phase 1 actually found" above.
- **2026-09-17** — First hardware sign-check session with the physical robot and user together: got the robot standing (recovered from a flaky IMU serial connection via a ROS restart), verified the ankle-roll servos are mechanically mirrored as expected, then ran the sign-check script repeatedly and kept seeing near-zero roll despite deliberate sideways tilts. Traced it to a real bug, not a test-procedure issue this time: **roll and pitch's accelerometer axes were swapped since the 2026-09-14 "confirmation"** — `accel_roll` is `atan2(ax, ay)`, not `atan2(az, ay)`. Confirmed with two clean, mechanically constrained tests (foot-lift lean vs. forward-toe lean) that each moved exactly one axis while the other stayed at baseline; the old "confirmed" data point turns out to match today's forward-lean signature exactly, meaning it was a mislabeled pitch test all along. `complementary_filter.py`, its tests, and `scripts/balance_sign_check.py` fixed; 258 tests pass. See "Verifying the real IMU's axis convention" above and `.agents/fixes/2026-09-17-imu-roll-pitch-axes-swapped.md`. The original sign-check question (does the correction actually help on real hardware) is still open — this session ran out of clean test attempts before getting a real answer with the corrected formula; that's the very next thing to do.
- **2026-09-21** — Resumed with the physical robot (4 days later, everything had to be restarted from scratch — Pi ROS launch, Mac server). **Single-shot sign check finally confirmed, both directions, on real hardware.** Rewrote `scripts/balance_sign_check.py` to read the IMU before *and* after one real correction (physical "feel" testing turned out not to be diagnostic — a tester's hand can't distinguish our few-degree correction from the robot's own much-larger stand-pose holding torque). Two false "wrong direction" results along the way, both traced to the disturbance not actually being held constant across the before/after window (tester still settling into the lean, or measuring from a leftover un-reset state) — not code bugs. Once the lean was held genuinely steady: left-foot-lift lean +5.28° → +3.96°, right-foot-lift lean -7.63° → -7.53°, both toward level. **This closes the last open item blocking hardware gain tuning.** Full account: "Hardware sign check" above. Next: tune gains by feel on hardware (needs a crash mat / soft test area first, per the Phase 3 checklist).
