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
| ⬜ | Weigh the robot (kitchen/postal scale) |
| ⬜ | Correct `body_link`'s mass in `assets/ainex/ainex.xml` for the missing battery/wiring weight |
| ⬜ | Confirm the onboard IMU responds — SSH to the Pi, run the manufacturer's sensor test script, note whether you get 6 floats (accel+gyro) or 9 (+magnetometer) |
| ⬜ | Two-scale standing balance check, to validate the corrected mass model |

## Phase 3 — Hardware integration

| | Item |
|---|---|
| ⬜ | Implement `GET /positions`-equivalent IMU access on the Pi (`backend/app/robot/pi/nodes/server.py` or a new node) — read the real IMU, return attitude + rate in the same shape `AttitudeReading` expects |
| ⬜ | Run `BalanceController` as its own always-on background loop/thread on the Pi, separate from `robot_server.py`'s request handlers (which block until a move finishes — see plan §3) |
| ⬜ | Tune gains by feel on hardware: robot standing still, no mimicry — "stands and resists a push" is the bar (plan §7's push-test procedure) |
| ⬜ | **Crash mat / soft test area in place before this phase starts** — early gain tuning on real hardware means falls are expected |

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
