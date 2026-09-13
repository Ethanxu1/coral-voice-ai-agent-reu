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
| ✅ | `ComplementaryFilter` (`backend/app/balance/complementary_filter.py`) — fuses raw accel+gyro into an `AttitudeReading`, same output shape `sim_source.py` produces, so `BalanceController` doesn't care which one fed it. 8 unit tests verify the filter math itself (convergence, tracks a known analytic rotation, unit conversion) using synthetic data. **Axis convention (which raw index is roll vs. pitch, which sign) is an assumption carried over from the sim's verified convention, NOT independently confirmed on real hardware** — this is the one thing here that still needs your hands on the robot, see "Verifying the real IMU's axis convention" below. |
| ⬜ | Deploy `/imu` to the Pi and run the axis-convention check (below) |
| ⬜ | Run `BalanceController` as its own always-on background loop/thread on the Pi, separate from `robot_server.py`'s request handlers (which block until a move finishes — see plan §3) |
| ⬜ | Tune gains by feel on hardware: robot standing still, no mimicry — "stands and resists a push" is the bar (plan §7's push-test procedure) |
| ⬜ | **Crash mat / soft test area in place before this phase starts** — early gain tuning on real hardware means falls are expected |

### Verifying the real IMU's axis convention

`ComplementaryFilter` assumes the real IMU's raw accel/gyro axes match the
same roll-about-X / pitch-about-Y convention already verified in sim (see
`sim_source.py`'s docstring) — a reasonable guess, not a confirmed fact.
Same kind of check as the sim's `test_balance_sim_source.py`, just done by
hand instead of by test:

1. Deploy the updated `server.py` to the Pi (scp → `docker cp` → `chmod +x`
   → restart `roslaunch`, same as always).
2. `curl http://<robot-ip>:9000/imu` a few times standing still — confirm
   you get `{"values": [9 numbers]}`, first 3 near `(0, 0, ±1)`-ish
   depending on mounting.
3. Tilt the robot forward (nose down) by hand and curl again. **If this
   project's pitch convention holds, that should read as an increasingly
   positive `accel_pitch = atan2(-ax, hypot(ay, az))`** — work it out from
   whichever of the first 3 values changes.
4. Tilt it to its own right side and repeat for roll
   (`atan2(ay, az)`).
5. If either comes out backwards, negate that formula (and the
   corresponding rate) in `complementary_filter.py` — one-line fix, not a
   rewrite — and note it here as confirmed.

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
- **2026-09-13** — Phase 2 done, all four items: weighed the physical robot (2.471 kg), two-scale stand-pose split (right 1.348 kg / left 1.131 kg, a real 217 g imbalance, visually confirmed against the robot's actual wiring/motherboard layout), corrected `body_link`'s mass in `ainex.xml` by moment balance (not eyeballed) to match, and confirmed the onboard IMU responds — `ainex_sdk`'s `imu_demo.py` returns 9 floats (accel/gyro/magnetometer), accel magnitude ≈1g at rest sanity-checked the reading. Next: Phase 3 (hardware integration) — wire `get_imu()` through a Pi-side HTTP route, run the balance loop as its own always-on process there, tune gains by feel with the robot standing still.
