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
| ✅ | **Closed-loop verification: the correction direction is confirmed correct**, 2026-09-14, **re-confirmed 2026-09-22 against a fixed baseline** (see below — the original test had a confound, now resolved; the conclusion itself holds). See "What Phase 1 actually found" below — resolves the question the 2026-09-09 headless attempt left open. |
| 🚧 | **Gains partially tuned; provisional pending re-verification, 2026-09-22.** `max_rate_rad_per_s` raised 2.0 -> 3.0 in earlier tuning; a 2026-09-22 fix (`SimBalanceLoop`'s `r_ank_roll` baseline bug — see "RESOLVED" note below "Integral term attempt") means this and the other prior gain comparisons were measured against a confounded baseline. The controller's real, verified value turns out to be **damping the recovery transient** (no overshoot past level), not closing a steady-state residual — the "~0.3° residual" this row used to describe was largely the confound itself, not a real gap needing an integral term. Not urgent to redo the tuning sweep since nothing is currently broken; flagged for whenever gain tuning is revisited. See "What Phase 1 actually found" and the RESOLVED note below "Integral term attempt" for the full account. |
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

### Integral term attempt (2026-09-21) — infrastructure added and tested, NOT validated

Attempted to close the steady-state residual (real on both sim and
hardware — see "Continuous loop deployment" below) by adding an
integral term to the ankle channels. **Status: the code is real, unit
tested (`ankle_ki` defaults to 0.0, a true no-op — every existing test
passes unchanged), and mechanically correct (accumulates, clamps at
`integral_max_rad`, resets with the rest of the controller's state) —
but live sim testing found it does NOT close the residual, and a
follow-up diagnostic surfaced a genuinely confusing, unresolved
contradiction. Do not enable `ankle_ki` in production until this is
sorted out.**

**What was built:** `BalanceGains.ankle_ki` (default 0.0) and
`integral_max_rad` (anti-windup cap, default 0.05 rad), ankle-only (not
hip — the residual is squarely an ankle-level issue). One real design
fix made along the way, itself confirmed correct: the integral
accumulates the RAW attitude reading, not the deadbanded error P/D
use — the residual it exists to close (a few tenths of a degree) is
itself *smaller* than `deadband_rad` (0.57°), so gating the integral on
the same deadbanded value P/D use meant it had literally nothing to
accumulate at the exact error size it was added for. 7 new unit tests
(`TestIntegralTerm` in `test_balance_controller.py`) cover accumulation,
clamping, the deadband-independence fix, reset, sign, and hip's
continued lack of integral state.

**What live sim testing found:** with `ankle_ki=0.1`, `integral_max_rad=0.05`,
pushing the sim and watching the settled roll over 20 seconds: the
integral correctly accumulated and hit its cap (~9s), but the *settled
roll got worse*, not better, going from the P+D-only baseline (~-0.3°)
to ~-0.4 to -0.5° with the integral active. Raising `integral_max_rad`
to 0.08 made it worse again (~-0.5 to -0.6°) — the opposite of the
expected "more authority closes the gap" relationship.

**Follow-up diagnostic, and the real puzzle:** to isolate whether this
was an integral-specific bug or something more fundamental, tested
holding the ankle-roll joints at a *fixed*, non-integral offset
(bypassing `BalanceController` entirely) and measuring where the robot
settles — done twice, the second time with a proper reset and 5-second
settle between each measurement to rule out test contamination. Both
runs agreed: a **positive** fixed ankle-roll offset made the (already
negative) settled roll *more negative*, and a **negative** offset moved
it toward (and past) zero. That's the opposite sign relationship the
existing, extensively-verified P-term formula assumes — and directly
contradicts the closed-loop sign checks already confirmed multiple
times, independently, in both sim (2026-09-14) and on real hardware
(2026-09-21, both directions) using that exact formula.

**This contradiction is unresolved.** The fixed-offset diagnostic is a
much newer, less-verified test than the closed-loop and real-hardware
sign checks, and a *static* held offset may not have the same
relationship to settled body roll that a *dynamic*, transient
push-response does (real rigid-body contact/support-polygon dynamics
are not necessarily simple or linear) — so the more likely explanation
is that the fixed-offset test isn't a valid way to check the
controller's sign, not that the extensively-verified P-term is
secretly backwards. But this is a hypothesis, not a confirmed
explanation, and it was not run to ground. Reverted `ankle_ki` to its
safe 0.0 default rather than ship or continue debugging this at the end
of an already very long session.

**Next time this is picked up:** don't just retry integral tuning —
first resolve the fixed-offset contradiction above, since it calls the
whole approach into question until explained. A cleaner test: drive the
sim with a *slow, controlled ramp* of ankle-roll offset (not discrete
jumps) while continuously logging settled roll, to see the full
static offset -> roll relationship as a smooth curve rather than a few
noisy point samples — that would also reveal if the relationship is
even monotonic, which the current data doesn't establish with
confidence.

### RESOLVED (2026-09-22): the contradiction was a real bug, not a sign problem — and it retroactively changes a lot

**Root cause found: `SimBalanceLoop` had the exact same `r_ank_roll`
baseline bug as `balance_loop.py`'s 2026-09-21 fix
(`.agents/fixes/2026-09-21-balance-loop-baseline-rad.md`), just never
ported to the sim file when it was written the same day (2026-09-14).**
`_baseline_rad` assumed `0.0` for every roll joint; `r_ank_roll`'s true
stand-keyframe value is `-0.0698` rad. This meant the sim loop was
injecting a constant, spurious ~4° disturbance onto that one joint
*every time it ran*, completely independent of the controller's own
computed correction — which could be exactly zero and this would still
fire. Fixed in `sim_loop.py`, same pattern as the Pi-side fix
(`HW_STAND_RAD.get(j, 0.0)`), with 4 new unit tests
(`test_balance_sim_loop.py`) that would have caught it (verified by
reverting the fix and confirming the exact expected failure before
reapplying). Fix entry: `.agents/fixes/2026-09-22-sim-loop-baseline-rad.md`.

**This is bigger than the integral term's puzzle — it retroactively
confounds essentially every sim closed-loop test run against this file
since 2026-09-14,** including the original "does the correction help"
resolution and the `max_rate_rad_per_s`/`ankle_kp`/`ankle_kd`/
`deadband_rad` gain-tuning work documented above and in the Log.
Retested with the fix, from a properly-settled baseline (see the note
on standalone-script settle time below, a second, separate bug found
along the way):

```
Natural resting lean (loop off, no push):            ~+0.50 to +0.53°
Push 1.0 rad/s, loop OFF (P+D never runs):            settles ~+0.53 to +0.56° -- unchanged
Push 1.0 rad/s, loop ON, P+D only (baseline FIXED):   settles ~+0.53 to +0.68° -- also unchanged
Push 3.0 rad/s, loop ON, P+D only (baseline FIXED):   settles ~+0.46 to +0.68° -- also unchanged
```

The controller now correctly does **nothing** at this residual — because
+0.5° is *inside* `deadband_rad` (0.57°), exactly as designed. The
previously-documented "45% reduction in settled tilt, overshoot past
level to -0.22 to -0.35°" was, at least in significant part, the
baseline bug's own injected ~4° disturbance being counteracted by the
controller's real P-term — not a faithful demonstration of correcting a
genuine residual from a clean start.

**So what does the controller actually do, now that this is fixed?**
Tested at 8.0 rad/s (near the previously-established ~9 rad/s fall
threshold), loop off vs. on, both starting from the same clean,
properly-settled baseline:

```
Loop OFF: peaks ~+11°, then OSCILLATES hard -- swings past level to -3.19° at t~1.2s,
          bounces back up, messily settles near +0.5° by t~12-18s.
Loop ON:  peaks ~+12°, then decreases SMOOTHLY AND MONOTONICALLY -- no overshoot past
          level at all -- reaching the same +0.5-0.7° settled point by t~18-27s.
```

**Both converge to the same final resting point either way** — because
that point was never really broken to begin with (it's inside the
deadband). **The controller's real, valuable contribution is damping
the recovery transient** — preventing the wild oscillation passive
dynamics alone produces, not reaching a different final angle. This is
arguably a *more* valuable property for a real robot (a large swing
through level, even if it eventually recovers, is closer to an actual
fall than a smooth, monotonic return) than the "closes the residual"
framing this whole investigation had been chasing.

**What this means for the integral term:** there was never a real,
deadband-exceeding residual in sim for it to close — which is exactly
why enabling it did nothing meaningful (not "backwards," just acting on
a case that didn't need fixing). Its actual use case — a real,
deadband-exceeding bias — is what hardware genuinely has (~2.3-4°,
confirmed 2026-09-21), not what sim's small, deadband-covered natural
asymmetry has. Testing it further needs either a real hardware trial or
a deliberately-constructed sim scenario (e.g., an artificially larger
mass offset), not sim's own natural resting lean.

**Separate, smaller bug also found along the way:** a standalone
verification script only waited 0.3s after constructing a fresh
`AiNexSimulator()` before pushing/testing — not enough time to reach
true equilibrium (a fresh sim needs ~2-2.5s to settle from construction,
confirmed by direct measurement). This is a test-methodology issue, not
a code bug, but it's what produced the initial (wrong) "gets worse as
integral authority increases" and "sign looks backwards" readings
before the real baseline bug was found. **Lesson for future standalone
diagnostic scripts:** always give a freshly-constructed simulator 2-3
seconds to settle (or call `reset_pose()` and wait) before applying any
push, offset, or measurement — the live HTTP server's `/reset` +
several-second waits already do this correctly, which is why the
HTTP-based trials in this session gave trustworthy results while the
ad-hoc scripts initially didn't.

**Status of prior gain-tuning conclusions (2026-09-09 through
2026-09-15):** treat as provisional, not settled. The qualitative
lessons about individual parameters (e.g., large `ankle_kd` jumps
causing oscillatory instability) likely still hold as general
PID-tuning facts, but specific comparisons ("3.0 is better than 2.0")
were reached against confounded data and should be re-verified against
the now-fixed baseline before being trusted for anything precision-
sensitive. Not urgent to redo given none of those tuned values are
currently causing a known problem — flagged here so a future session
knows the history, not as a demand to immediately redo weeks of tuning.

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
| 🚧 | **Continuous `BalanceLoop` deployed and running on real hardware, 2026-09-21 — real limitation found, not yet resolved.** First-ever deployment hit and fixed two real bugs (see "Continuous loop deployment" below): a Python 3.8 compatibility issue that blocked the loop from loading at all, and a missing IMU zero-bias calibration + wrong per-joint baseline. Both fixes verified working, but a real, reproducible ~2.3-2.5° residual persists regardless of calibration quality (confirmed by recalibrating from a much cleaner, well-settled baseline — same residual came back) — and on real hardware, unlike in sim, this residual visibly manifests as one foot's edge staying lifted, not an imperceptible lean. This is the sim-predicted PD-droop residual (no integral term, real constant mass-asymmetry bias — same open item as the sim-side residual documented in "What Phase 1 actually found" above), just more visually obvious here than expected. A real push (before the resting-state fixes) was recovered from successfully — "stands and resists a push" met once — but the resting-state residual means this checklist item isn't fully clean yet. Sim-derived gains used as-is; no hardware gain tuning attempted. |
| ✅ | **Crash mat / soft test area in place, 2026-09-21** — confirmed before the continuous loop was ever started. |

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

### Continuous loop deployment

**First-ever deployment of `BalanceLoop` to real hardware, 2026-09-21.**
Six files (`server.py`, `balance_loop.py`, `controller.py`,
`complementary_filter.py`, `hardware_angle_utils.py`, `servo_config.py`)
deployed via the usual scp -> `docker cp` -> `chmod +x` cycle. Two real
bugs surfaced, neither one a sim-vs-hardware gain difference — both
genuine code defects that had simply never been exercised before:

1. **Python 3.8 incompatibility.** `hardware_angle_utils.py` and
   `servo_config.py` both use bare `dict[...]`/`tuple[...]` module-level
   type annotations without `from __future__ import annotations` —
   fine on the Mac (Python 3.12), fatal on the Pi (Python 3.8, where
   that syntax needs the future import or it's evaluated eagerly and
   raises `TypeError: 'type' object is not subscriptable`). Neither
   file had ever actually been imported on the Pi before this session —
   the whole balance-controller effort had been Mac/sim-only until now.
   Fixed by adding the future-annotations import to both, matching
   `controller.py`/`complementary_filter.py`'s existing correct pattern.
   Fix entry: `.agents/fixes/2026-09-21-pi-py38-bare-generic-annotations.md`.

2. **No IMU zero-bias calibration, plus a wrong per-joint baseline.**
   Once the loop actually loaded and ran, the user noticed it holding
   an unwanted foot-edge-lift continuously, even with the robot
   undisturbed. Investigated rather than dismissed: stopping the loop
   and resetting the ankles to their true commanded neutral, the robot
   visually looked level and standing straight — while the IMU still
   reported ~4° of roll in that exact state. That's a sensor-mounting
   offset, not real tilt, and the controller had no way to tell the two
   apart. A second, related bug was found while simulating the fix:
   `r_ank_roll` has a real, nonzero `HW_STAND_RAD` entry (-0.0698 rad,
   a genuine asymmetry vs. `l_ank_roll`'s 0.0) that `BalanceLoop`'s
   baseline dict ignored, silently miscalibrating that one joint's
   resting pulse even once the bias fix alone would have zeroed the
   controller's own error. Both fixed and verified first via a
   simulated fake-board test (both ankles converge to and hold exactly
   their commanded resting pulse with a constant reading), then live on
   the robot: resting offset dropped from ~4° to ~2.25° and stabilized
   — a few seconds of small settling twitches, then stopped on their
   own. Fix entries: `.agents/fixes/2026-09-21-balance-loop-imu-zero-bias.md`,
   `.agents/fixes/2026-09-21-balance-loop-baseline-rad.md`.

**The remaining ~2.25° isn't a bug.** With sensor bias removed, this
matches the same residual-lean pattern found extensively in sim
testing: a pure PD controller (no memory of how long it's been
leaning) always leaves a small steady error against a *constant* bias
torque, and this robot has one — the independently measured ~217g
right-side-heavy mass asymmetry from Phase 2. Removing that residual
fully would need an integral term, same open item as the sim-side
steady-state residual documented above, not something to chase via
these bug fixes.

**A real push, applied before the resting-state fixes above, was
successfully recovered from** — roll climbed from ~4° to ~8-9° after a
moderate sideways push, plateaued briefly (still actively correcting),
then fully returned to the ~4° baseline within about 10 seconds. That
meets the plan's "stands and resists a push" bar once, with sim-derived
gains, no tuning needed yet — worth re-confirming with the calibrated
version of the loop before calling hardware gain tuning unnecessary.

**Follow-up the same session: the resting residual is real and
reproducible, not a calibration-timing artifact.** After the fixes
above, the user reported the robot's foot still visibly lifted at rest
— not satisfied by the "this is expected PD droop" explanation alone,
which was the right instinct to push back on. Investigated further
rather than repeating the same explanation: found the reset-to-start
window was tight (`RESET_TO_STAND_MS`=1000ms, only ~1.5s total wait
before starting the loop) — a real possible cause, since a calibration
sampled while the robot is still mid-settle would bake in a wrong zero.
Redone with a much longer, verified-stationary settle (waited until
three consecutive readings agreed, ~4s+, landing on a much smaller
-1.0° baseline this time, vs. the earlier ~4°) — started the loop from
that clean baseline, and **it drifted right back to ~2.5°**, landing in
essentially the same range as before regardless of the very different
starting calibration. That rules out calibration timing as the
explanation; the system converges to roughly the same residual
independent of where it starts, consistent with a real closed-loop
equilibrium (the PD-droop theory), not a one-time measurement error.

**Conclusion:** the fixes earlier this session (zero-bias calibration,
correct `r_ank_roll` baseline) are real and working — they removed a
~4° sensor-bias-driven offset that had nothing to do with genuine
control behavior. What's left is the genuine, sim-predicted residual
against the robot's real mass asymmetry, which this roll-only PD
controller cannot fully eliminate without an integral term. The
difference from sim: a couple degrees of residual there looked
"basically settled"; on real hardware, because the ankle correction is
mirrored across both feet resting on a genuinely rigid floor, that same
residual apparently resolves as one foot's edge staying visibly
lifted rather than an imperceptible torso lean — a real, legitimate
observation, not something to explain away. Decided to stop here for
this session rather than start designing an integral term (real new
scope, its own risks like windup) this late in an already long,
physically-involved session. **Open for next time:** either accept
this residual as a known limitation (it's a couple degrees, nowhere
near a stability concern) or design and carefully test an integral
term addition.

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
- **2026-09-21** — Resumed with the physical robot (4 days later, everything had to be restarted from scratch — Pi ROS launch, Mac server). **Single-shot sign check finally confirmed, both directions, on real hardware.** Rewrote `scripts/balance_sign_check.py` to read the IMU before *and* after one real correction (physical "feel" testing turned out not to be diagnostic — a tester's hand can't distinguish our few-degree correction from the robot's own much-larger stand-pose holding torque). Two false "wrong direction" results along the way, both traced to the disturbance not actually being held constant across the before/after window (tester still settling into the lean, or measuring from a leftover un-reset state) — not code bugs. Once the lean was held genuinely steady: left-foot-lift lean +5.28° → +3.96°, right-foot-lift lean -7.63° → -7.53°, both toward level. **This closes the last open item blocking hardware gain tuning.** Full account: "Hardware sign check" above.
- **2026-09-21 (continued)** — Crash mat confirmed in place; deployed `BalanceLoop` to the Pi for the first time ever (continuous, not one-shot). Hit and fixed two real bugs: a Python 3.8 compatibility issue that blocked the loop from loading at all (`hardware_angle_utils.py`/`servo_config.py` missing `from __future__ import annotations`), and a missing IMU zero-bias calibration plus a wrong per-joint baseline that together caused the loop to hold an unwanted foot-edge-lift even at true rest (traced by the user directly observing the robot looked level with ankles at neutral despite the sensor disagreeing — trusted that over the numbers). Both fixed and verified via simulation, then live: resting offset dropped from ~4° to ~2.25° and stabilized on its own after brief settling twitches. A real push (before the resting-state fixes landed) was successfully recovered from, meeting the plan's "stands and resists a push" bar once already. Full account: "Continuous loop deployment" above.
- **2026-09-21 (continued, final)** — User correctly pushed back that the foot-lift still hadn't fully gone away — didn't accept the earlier "expected PD droop" explanation at face value. Investigated further: found the reset-to-loop-start window was tight enough that calibration might have sampled a still-settling reading; redone with a verified-stationary, much longer settle (new baseline -1.0°, vs. the earlier ~4°) — but the loop drifted right back to ~2.5° anyway, ruling out calibration timing as the cause. Confirms this is a genuine, reproducible closed-loop equilibrium (the same PD-droop residual predicted in sim), just more visually obvious on real hardware than in sim, since the mirrored ankle correction on a rigid floor resolves as a visibly lifted foot edge rather than an imperceptible lean. Stopped the loop and reset the robot to a safe stand.
- **2026-09-21 (continued, integral term attempt)** — User asked to add an integral term to close the residual. Built it (ankle-only, `ankle_ki`/`integral_max_rad`, defaults to 0.0/off, 7 new unit tests) and, per the project's own established practice, verified in live sim before trusting it — where it found real problems, not a quick win. First live test: accumulating the deadbanded error (same as P/D) gave the integral literally nothing to work with, since the residual itself is smaller than the deadband — fixed by switching to raw-attitude accumulation. Second live test: even fixed, the integral didn't close the residual — it made it *worse* as its authority (`integral_max_rad`) increased. A follow-up fixed-offset diagnostic (bypassing the controller) then surfaced a genuinely confusing contradiction: it suggested the ankle-roll-to-body-roll sign relationship might be opposite to what the extensively-verified P-term formula assumes — directly conflicting with the closed-loop and real-hardware sign checks already confirmed multiple times independently. Rather than keep guessing at the end of an already very long session, reverted `ankle_ki` to its safe 0.0 default and documented the full, unresolved puzzle for next time. Full account: "Integral term attempt" above.
- **2026-09-22** — Resolved the previous entry's contradiction: `SimBalanceLoop` had the exact same `r_ank_roll` baseline bug as `balance_loop.py`'s 2026-09-21 fix, just never ported to the sim file. It was injecting a constant, spurious ~4° disturbance onto `r_ank_roll` every tick, independent of the controller's own computed correction — confounding essentially every sim closed-loop test since 2026-09-14. Fixed (4 new unit tests, verified they'd catch the bug), and re-testing revealed something bigger than a bug fix: the controller's real, valuable behavior is **damping the recovery transient** (no overshoot past level after a push) rather than closing a steady-state residual — there wasn't really a residual to close in sim once the confound was removed (the natural ~0.5° lean sits inside the deadband on its own). This fully explains why the integral term "didn't help" — it was acting on a case that didn't need fixing. Also found and noted a smaller, separate test-methodology bug (standalone scripts need 2-3s settle time after constructing a fresh simulator, not 0.3s). Prior gain-tuning conclusions (09-09 through 09-15) flagged as provisional pending re-verification against the fixed baseline, not urgent to redo. Full account: "RESOLVED" note under "Integral term attempt" above; fix entry `.agents/fixes/2026-09-22-sim-loop-baseline-rad.md`.
