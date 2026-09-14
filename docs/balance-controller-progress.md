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
| 🚧 / ⛔ | **Wiring `BalanceController` into the live sim loop, and closed-loop verification that it actually helps — attempted, not resolved.** See "What Phase 1 actually found" below. Not wired into `AiNexSimulator`'s running physics loop yet — that step is intentionally on hold until the open item below is sorted out, so a broken/backwards correction can't reach the live app. |
| ⬜ | Get gains into a reasonable range (blocked on the above) |
| ⬜ | Confirm ankle-only handles small pushes, hip visibly engages on larger ones, in the sim viewer |

### What Phase 1 actually found (read this before continuing)

The sensor reading is solid — verified against known rotations, not assumed.
The controller's *correction*, tested in closed-loop headless physics
(reset to stand, apply a disturbance, run the controller each tick,
compare final tilt against an uncontrolled baseline), **did not clearly
help with the current placeholder gains** — in one run it made things
worse. Chasing this further with single-joint headless probes (nudge one
ankle joint, see how attitude responds) produced messy, hard-to-interpret
results: even ankle-*pitch* alone produced a large pitch-*and*-roll
response, which reads more like transient/contact-dynamics noise than a
clean linear relationship a blind script can reliably untangle.

This is very plausibly the "sim actuator response isn't calibrated,
tune by iterating" problem the plan already expected (§7) — not
necessarily a wrong sign — but it hasn't been isolated. **Recommended
next step: do this with the sim viewer open**, watching the robot
respond to a nudge in real time, rather than more blind headless
probing — a human eye will separate "wrong sign" from "right sign, needs
gain tuning" from "coupling I didn't account for" far faster than another
script. Full data from what was tried is in the 2026-09-09 session log
(`.agents/logs/`) if picking this back up.

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
| ⬜ | Run `BalanceController` as its own always-on background loop/thread on the Pi, separate from `robot_server.py`'s request handlers (which block until a move finishes — see plan §3) |
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
- **2026-09-14** — Deployed `/imu` to the Pi, confirmed it works. Roll axis convention confirmed against real hardware after several failed attempts (robot unpowered, then "resting on a table" protocol, both gave uncontrolled/inconsistent baselines) — with the robot actively torque-holding `stand`, real tilt data confirmed `accel_roll = atan2(az, ay)`, 3 independent trials agreeing (the original formula's axis *pairing* was wrong, not just its sign — real "up" is Y, not Z). Pitch: 5 attempts, all inconclusive or contradictory — the clearest one (a real, confirmed toe-pivot forward lean) read as 97° of *roll*, not pitch. Deliberately deferred rather than guessed at — see "Verifying the real IMU's axis convention" for the full account and working theory (the robot's own right-heavy mass asymmetry may make pitch impossible to isolate from a by-hand test). `complementary_filter.py` and tests updated to the confirmed roll formula; pitch stays an explicitly-flagged unverified placeholder.
- **2026-09-13** — Phase 2 done, all four items: weighed the physical robot (2.471 kg), two-scale stand-pose split (right 1.348 kg / left 1.131 kg, a real 217 g imbalance, visually confirmed against the robot's actual wiring/motherboard layout), corrected `body_link`'s mass in `ainex.xml` by moment balance (not eyeballed) to match, and confirmed the onboard IMU responds — `ainex_sdk`'s `imu_demo.py` returns 9 floats (accel/gyro/magnetometer), accel magnitude ≈1g at rest sanity-checked the reading. Next: Phase 3 (hardware integration) — wire `get_imu()` through a Pi-side HTTP route, run the balance loop as its own always-on process there, tune gains by feel with the robot standing still.
