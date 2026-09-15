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
| 🚧 | **Gains partially tuned** — `max_rate_rad_per_s` raised 2.0 -> 3.0, cutting peak post-push overshoot roughly in half (-1.96° -> -0.93°) with no instability; this was the actual bottleneck, not `ankle_kd` (raising kd alone did nothing measurable). See "2026-09-15: gain tuning attempt" below. Still open: the ~0.3° steady-state residual (expected PD droop against the mass-asymmetry bias — needs `ankle_kp` or an integral term, neither tried yet). |
| ⬜ | Confirm hip visibly engages on larger pushes, in the sim viewer (ankle-only engagement already confirmed by the pushes below — both stayed under `ankle_saturation_rad`) |
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
move, not where it settles; that residual is `ankle_kp`/integral-term
territory, still untried.

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
| ✅ | `ComplementaryFilter` (`backend/app/balance/complementary_filter.py`) — fuses raw accel+gyro into an `AttitudeReading`, same output shape `sim_source.py` produces, so `BalanceController` doesn't care which one fed it. 10 unit tests (8 synthetic + 2 locking in real hardware readings below). |
| ✅ | Deployed `/imu` to the Pi and confirmed it responds — `[server] IMU board ready`, doesn't affect `/move`. |
| ✅ | **Roll axis convention CONFIRMED against real hardware, 2026-09-14.** Original formula guess was wrong in a bigger way than a sign flip — the real board reads "upright" as `ay≈1` (Y is the resting up-axis), not `az≈1` as a generic IMU tutorial formula assumes. Real data: standing → roll ≈3° (near level, correct), robot physically tilted toward its own right → roll ≈81° (large, correct direction of change). Fixed formula: `accel_roll = atan2(az, ay)`. |
| ⛔ | **Pitch axis convention NOT confirmed after 5 real attempts — deliberately deferred, not guessed at.** `accel_pitch = atan2(ax, ay)` stays an unverified placeholder; do not trust it. A real, unambiguous forward tilt (heels lifted, confirmed) still came out reading as 97° of *roll*, not pitch — `X` hasn't shown a real signal in any hand-applied test tried. Likely needs a more controlled test (can't cleanly isolate by hand on this robot, possibly due to its own right-heavy mass asymmetry) — see "Verifying the real IMU's axis convention" below for the full account and recommended next approach. |
| ✅ | `BalanceLoop` (`backend/app/robot/pi/nodes/balance_loop.py`) — background thread wiring `BalanceController` to the real IMU and the body service, **roll channels only** (pitch discarded every tick — unverified, see above). Off by default; `POST /balance/start`/`stop` + `GET /balance/status` added to `server.py`. Deploy chain and end-to-end tick logic verified by simulation (fake board + real recorded IMU readings, run outside any Pi) — confirmed the correction converges smoothly and the two-tier ankle→hip handoff engages correctly. **Not yet deployed to the Pi or run against real servos.** |
| ⬜ | **Before turning this loop on for real:** the single-shot sign check — manually tilt the robot, compute what the controller would command, send it as one `/move`, confirm it corrects rather than worsens the lean. Closes Phase 1's still-open question (does the correction direction actually help) using real data instead of more sim probing. |
| ⬜ | Tune gains by feel on hardware: robot standing still, no mimicry — "stands and resists a push" is the bar (plan §7's push-test procedure) |
| ⬜ | **Crash mat / soft test area in place before this phase starts** — early gain tuning on real hardware means falls are expected |

### Verifying the real IMU's axis convention

**Roll: done (2026-09-14).** Real data, robot actively torque-holding
`stand` (this matters — the first attempts used an unpowered/manually-posed
robot and gave inconsistent, unusable baselines):

```
standing: ( -0.023, 0.997, 0.054 )  -> roll = atan2(0.054, 0.997) ≈ 3°
right:    ( -0.024, 0.151, 0.981 )  -> roll = atan2(0.981, 0.151) ≈ 81°
```

Confirms `accel_roll = atan2(az, ay)` — note this replaced the original
guess (`atan2(ay, az)`), not just a sign flip on it; the real board's
resting "up" axis is Y, not Z.

**Pitch: still unconfirmed after 5 attempts on 2026-09-14 — deliberately
not guessed at, deferred rather than forced.** `accel_pitch = atan2(ax, ay)`
remains an unverified placeholder in the code; do not trust it.

What was tried, in order: (1) held-tilt while standing, too gentle, read
as noise; (2)-(3) same, still noise, even after confirming stand was
actively torque-held; (4) a firmer standing-tilt attempt, still noise;
(5) a real, unambiguous toe-pivot forward lean (heels lifted off the
desk, confirmed by the user) — this one finally showed a large signal,
but run through the formulas it came out as **97° of roll**, not pitch
(`ax` stayed at -0.055, the same near-zero range as every prior test; `ay`
and `az` moved the way a *roll* reading does). `X` has not shown a
meaningful signal in any of the ~10 real-hardware readings collected this
session, across every tilt direction attempted.

Working theory, not confirmed: the robot's own mass is asymmetric (right
side heavier — see the 2026-09-13 `body_link` mass correction), so a
forward tip may naturally introduce a real sideways component as it's
applied by hand, contaminating any attempt to isolate pitch alone. A
by-hand test may not be able to cleanly separate these on this
particular robot.

**Recommended path when this is picked back up:** don't repeat more
ad-hoc hand tilts — get a more controlled forward push (e.g. two points
of symmetric support so it can't twist sideways while tipping, or test
it once the balance loop exists and can log its own small forward nudges
during Phase 3/4 hardware tuning) rather than continuing to guess from
improvised data.

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
- **2026-09-15 (continued, again)** — Tested the working theory from the `ankle_kd` dead end directly: swept `max_rate_rad_per_s` (2.0 -> 3.0 -> 4.0) with `ankle_kd`/`ankle_kp` back at defaults. Confirmed it — 3.0 cut peak post-push overshoot roughly in half (-1.96° -> -0.93°) with no instability; 4.0 was slightly worse than 3.0 (diminishing returns, as expected once a parameter's helpful range is found). Kept `max_rate_rad_per_s = 3.0` as the new default — first real, kept gain change from this tuning round. Steady-state residual (~-0.3° off true level) is untouched by this parameter and remains the next open item, likely needing `ankle_kp` or an integral term. Full trace in "What Phase 1 actually found" above.
