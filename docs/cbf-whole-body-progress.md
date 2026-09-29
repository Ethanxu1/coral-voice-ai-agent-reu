# CBF / Whole-Body Safety Layer — Progress

Tracks a new, **separate** safety layer: a Control Barrier Function (CBF) 
that constrains whatever pose `follow`/mimicry
wants to command, so it automatically holds back before the robot would
fall — rather than the current all-or-nothing "refuse the whole move"
check, and specifically covering the live-follow path, which currently
has **no** safety check applied to it at all (see
`docs/balance-controller-progress.md` Phase 4, "Route the live-follow
path through `collision_checked_targets()`").

**Explicit scope decision (2026-09-22):** this does NOT touch or
replace the existing ankle/hip standing-balance controller
(`backend/app/balance/controller.py`) — that stays as-is, already
tested on real hardware. CBF is built and evaluated *alongside* it, as
a comparison, with the existing controller as the safe fallback if CBF
isn't ready in time.

**Status legend:** ✅ done · 🚧 in progress · ⬜ not started

---

## Why this is a different problem than what already exists

`StabilityChecker` (`backend/app/collision/stability_checker.py`)
already answers "would this pose make the robot fall?" — but it does so
by running a ~2.5-second physics rollout (1s ramp + 1.5s settle) per
check. That's fine for a one-time check before a discrete pose, but far
too slow to run on every frame of continuous real-time mimicry — which
is exactly why the live-follow path currently skips any check at all.

A CBF-based approach needs a safety signal that can be evaluated
**instantly**, every frame, cheap enough for real-time use. The
standard whole-body answer to "is the robot about to fall" that's fast
to compute: is the robot's **center of mass**, projected onto the
ground, still within the **support polygon** (the area enclosed by
whichever feet are actually touching the ground)? If yes, the robot is
statically stable; if no, gravity will tip it over. Both quantities are
cheap, direct reads from MuJoCo's own physics state — no rollout
needed.

## Phase 0 — Core safety-function math (software only, sim-agnostic style)

| | Item |
|---|---|
| ✅ | Center-of-mass reader (`backend/app/balance/cbf.py`, `get_center_of_mass`) — wraps MuJoCo's built-in `subtree_com` |
| ✅ | Support-polygon builder (`get_support_polygon`) — reads the existing `l_foot1_floor_found`/`l_foot2_floor_found`/`r_foot1_floor_found`/`r_foot2_floor_found` contact sensors to find which foot pads are actually touching the ground, computes each contacting pad's four corners in world space from its known box geometry, returns their convex hull (a small, dependency-free `_convex_hull_2d` — deliberately not scipy, which isn't an explicit project dependency) |
| ✅ | Signed-distance function (`signed_distance_to_polygon`) — the CBF "h(x)": positive when a point is inside a polygon (the margin, in meters), negative when outside. `stability_margin()` combines all three into the one function most callers need. |
| ✅ | 14 unit tests (`backend/tests/test_cbf.py`) — pure geometry (hull, signed distance) with plain coordinates, no MuJoCo; real-model integration using the actual AiNex model, not a mock |

### A real finding from writing the tests, not an assumption

Settled standing steady-state contact is **not** "all four foot pads
touching" — `r_foot1` (the right foot's larger, front pad) never
regains ground contact once truly settled. Confirmed by sweeping
settle time from 10 to 2000 physics steps: the contact pattern is
still visibly changing out past 400 steps and only becomes stable and
repeatable from ~750 steps (1.5s) onward. This is a real consequence of
the robot's known right-side-heavy mass asymmetry (independently
confirmed by weighing the physical robot — see
`docs/balance-controller-progress.md` Phase 2), not a sensor glitch or
a bug in this code. The tests assert the real 3-pad pattern
(`l_foot1`, `l_foot2`, `r_foot2` in contact; `r_foot1` not), not an
idealized 4-pad assumption — and `signed_distance_to_polygon`'s
`stability_margin()` is still comfortably positive standing normally
with only 3 pads, confirming the safety function handles this
correctly rather than needing all four to work at all.

**Lesson for whoever tunes this further:** settle time matters a lot
more here than the ~2-2.5s found for attitude settling elsewhere in
this project (`docs/balance-controller-progress.md`'s "RESOLVED" note)
— always sweep a range of step counts and look for a genuinely stable,
repeated pattern before trusting a contact-sensor reading in a test or
a live filter, rather than picking one number and assuming it settled.

## Phase 1 — Safety filter (not yet a full QP-based CBF controller)

A scoped, buildable first version rather than the full optimization-based
formulation: given a current (safe) pose and a desired (possibly unsafe)
target pose from mimicry, find the point along that path that stays
safe, closest to what was actually requested — the same "minimally
modify the nominal command to satisfy the constraint" idea a full CBF-QP
implements, without needing an external optimization solver dependency
for a first pass.

| | Item |
|---|---|
| ✅ | Safety-filter function (`backend/app/balance/safety_filter.py`, `SafetyFilter`) — mirrors `CollisionChecker`'s exact architecture (own headless model, interpolate current->target via `mj_forward`, back off to the last safe fraction if a step goes unsafe). A real bug found and fixed while building this: the free-floating base isn't in the hinge-joint dict a caller passes, and the raw `stand` keyframe isn't yet physically settled — both meant an early version reported the *unmodified stand pose itself* as unsafe. Fixed by settling once for real at construction time and using that as the reference baseline every check starts from. |
| ✅ | 9 unit tests (`backend/tests/test_safety_filter.py`) — a safe target (arm movement) passes through unchanged; an unsafe target (large hip-roll splay) gets scaled back to something with a real, verified-positive margin. A genuine surprise found while writing them: even a *small, endpoint-safe* ankle motion can have a real mid-motion dip (part of the foot briefly lifts partway through) — the filter correctly catches this, and the test asserts that real behavior rather than assuming "safe start + safe end = safe throughout." |
| ⬜ | Live sim test — **deliberately deferred to Phase 2.** Demonstrating this standalone would mean pushing an unsafe pose through the shared production `/move` endpoint, which already has its own separate collision/fall-check logic (`collision_checked_targets()`) that would interfere with a clean before/after comparison. Belongs naturally once this filter is actually wired into a live dispatch path (Phase 2), not forced through a confusing detour now. |

## Phase 2 — Wire into the live-follow path

| | Item |
|---|---|
| ✅ | Applied to `follow_controller.py`'s continuous stream via `FollowSafetyGate` (`backend/app/balance/safety_filter.py`) — the stateful adapter that carries "where the robot actually is" between frames, since `SafetyFilter` itself is stateless. Filters both the seed move (STAND → the human's first detected pose, the largest single move of a session) and every live tick. The existing ankle/hip standing-balance loop is untouched and unaffected either way. |
| ✅ | Measured cost before wiring it into a 20 Hz loop rather than assuming: **~1.9 ms per check worst case against a 50 ms tick budget (~4%)**, and ~0.11 s one-time construction. Cheap enough to run inline; no thread offload needed per tick, and the one-time build is done off the event loop. |
| ✅ | Toggle for the A/B comparison: `CORAL_ENABLE_FOLLOW_SAFETY` (default `true`). Set `false` to run follow mode unfiltered. Does not affect the ankle/hip controller in either position — the two layers are independent, which is what makes the comparison meaningful. |
| 🚧 | Compare behavior side-by-side. First real result below; a live/visual sim-viewer run is still outstanding. |

### First measured result: this filter only matters once legs are tracked

Ran realistic mimicry frames through the gate (not assertions — actual
margins):

| Frames | Stability margin | Filter fired? |
|---|---|---|
| Arms + head only, including fully-extended and overhead arms | 0.0381 → 0.0385 → 0.0384 | never |
| Legs engaged, progressive sideways lean | 0.0373 → 0.0155 → 0.0138 | yes, on the 3rd |

`ENABLE_LEG_TRACKING` defaults to **false**, so today's default follow
mode is arms + head only — and on that path the margin barely moves and
the filter never intervenes. Two consequences worth being explicit
about:

1. **Turning this on does not change the default demo's behavior.** It
   is effectively inert there, which is why defaulting it to `true` is
   low-risk rather than a gamble on new code.
2. ~~**Its actual value is that it makes leg tracking safe enough to
   enable.**~~ **⚠ RETRACTED 2026-09-29 — see Phase 2.5 below.** Tested
   against real dynamics the same day and this does **not** hold: the
   filter produced false negatives on exactly the asymmetric leg poses
   leg tracking would generate. **Fixed in Phase 2.5 the same day** —
   the filter now agrees with real dynamics 12/12, so this is no longer
   a blocker, but enabling leg tracking is still a live-demo behaviour
   change that hasn't been watched in the viewer.

Do not read the arms-only row as "the filter doesn't work" — it means
arm mass barely shifts this robot's center of mass, which is the
physically correct answer and matches Phase 0's finding that the
standing margin is dominated by foot contact and torso/leg geometry.

## Phase 2.5 — Base re-seating ✅ DONE (2026-09-29)

**Resolved. The filter now agrees with real dynamics on 12/12 test
poses, including every case it previously got wrong.**

### The fix

`SafetyFilter._settle_base()`: after applying a candidate pose, hold
every joint at its commanded value with the actuators and step physics
briefly, so what moves is the **base** — the body finds where it would
actually rest — rather than staying pinned at the standing reference.

Two parameters, both chosen from measurement rather than taste:

- `settle_damping=50.0`, applied to the shadow model *after* the
  reference stand is established (that has to happen under the model's
  real dynamics). This is principled, not a fudge: damping changes how
  fast equilibrium is reached, not where it is. Without it the settle
  **rings** — a first attempt measured the margin going negative at 25
  steps, positive again at 50 and 100, with plain standing reading
  unsafe at 400. Verdicts are now stable across 25/50/100/200 steps,
  which is the evidence it has actually converged.
- `settle_steps=25`. 10 was not enough (the knee case still read safe);
  25 onward is stable.

`num_steps` dropped 20 → 8 and `buffer_steps` 2 → 1. Each interpolation
step now costs a physics settle instead of one `mj_forward`, so 20
steps would be ~47ms against a 50ms tick. The buffer change keeps the
back-off at roughly the same *fraction* of the motion (12.5% at 8
steps vs. 10% at 20); left at 2 it was 25%, enough to collapse a
partially-safe move to "refuse everything".

### Result, production filter vs. real dynamics

Control first (robot commanded nothing → held stand). Then 12 poses,
filter verdict vs. what physics actually did:

| | |
|---|---|
| stand, arms wide, arms overhead | stays up → safe ✅ |
| hips −0.10 / −0.20 / −0.25 / −0.229·−0.225 | stays up → safe ✅ |
| **hips −0.229/−0.225 + l_knee 0.147** | **falls → UNSAFE ✅** (was +0.0199 "safe" — the false negative) |
| hips −0.35, hips −0.45 + knee 0.3 | falls → UNSAFE ✅ |
| **l_knee 0.3 alone, r_knee −0.3 alone** | **falls → UNSAFE ✅** (new cases, not previously tested) |

**12/12.** No false positives on arm/head poses — it did not simply
become over-restrictive.

### A Phase 1 conclusion this retracts

Phase 1 recorded a "genuine mid-motion dip" on a small ankle-roll
motion and asserted it in a test as real behaviour. **It was not
real.** With the base re-seated the margin along that whole path stays
between +0.034 and +0.038, nowhere near the threshold. It was the same
base-pinning artifact, in the false-*positive* direction — so pinning
was making the filter wrong in both directions, not just one. The test
now asserts the corrected behaviour
(`test_small_ankle_motion_is_safe_throughout`).

### Cost — the real tradeoff

| | Phase 2 (pinned) | Phase 2.5 (re-seated) |
|---|---|---|
| per `filter_targets` call, worst case | 1.9 ms | **14.8 ms** |
| share of the 50 ms tick | ~4% | **~30%** |

Within budget, but no longer negligible: this is blocking CPU work in
the event loop, ~200 `mj_step` calls per check. Accepted deliberately —
correctness of a safety filter beats its cost, and the follow loop
already tolerates dropped frames by design (it keeps only the freshest
pose). If it ever needs reclaiming, the obvious lever is warm-starting
the base across interpolation steps instead of resetting to the
baseline each time; not done, because it trades a correctness-relevant
invariant (no drift accumulation) for speed that isn't needed yet.

### ⚠ The Phase 2 heartbeat never worked (found 2026-09-29, fixed)

The first live session watching for `safety-holds` found **nothing in
`logs/server.log`** — not the heartbeat, not even "seeding initial
pose", despite five `follow_start` intents firing.

Cause: `follow_controller.py` logged through stdlib `logging` while
this app logs through **loguru**, and there is no `InterceptHandler`
bridging them anywhere in the backend. With no handler configured,
stdlib falls back to `logging.lastResort`, which only emits **WARNING
and above** — so every `logger.info` in that module was silently
dropped. Pre-existing for the module, but Phase 2's entire
observability story rested on it, so it shipped as a false claim.

Fixed: `follow_controller.py` and `safety_filter.py` now use loguru
(with `%`-style format strings converted to `{}`, which loguru
requires — left as `%s` they would have printed literally). The safety
numbers were also added to `CleanLogger.follow_tick`, since
`logs/clean_logs/` was the channel that *did* work throughout.

Guarded by `TestObservability` in
`backend/tests/test_follow_safety_wiring.py`.

**Any module added to the main server process should use loguru**,
not stdlib logging. The failure is completely silent.

### Still open

`ENABLE_LEG_TRACKING` remains off. The filter now handles leg poses
correctly in sim, which removes the blocker, but turning it on is a
live-demo behaviour change and has not been watched in the browser
viewer with a person in frame.

<details>
<summary>Original problem statement (kept for the record)</summary>

**Status when opened: the filter was not trustworthy for leg motion.**

The first real-dynamics test of the filter (2026-09-29) — everything
before this was `mj_forward`, i.e. kinematics with no gravity
integration or momentum — found a **false negative**, the dangerous
direction.

### What the dynamics test showed

Control first (this project has been burned by harness bugs before):
commanded nothing, robot held stand, roll +0.53° → +0.59°, CoM height
unchanged. Harness sound.

Sweep of a symmetric sideways lean, filter verdict vs. what physics
actually did:

| Lean (hip roll) | Filter says | Real physics | Correct? |
|---|---|---|---|
| 0.10 / 0.20 / 0.25 | allowed | stayed up | ✅ |
| 0.30 | held back | stayed up | ✅ conservative (safe direction) |
| 0.35 / 0.45 | held back | **fell** | ✅ |

That part is a genuinely good result — the filter's boundary sits just
inside the real one, erring safe. **But** the pose it *substituted* for
a rejected request fell too:

| Pose | Filter margin | Real physics |
|---|---|---|
| `l_hip_roll -0.229, r_hip_roll -0.225, l_knee 0.147` (the filter's own "safe" substitute) | **+0.0199 (safe)** | **fell, at every ramp rate** |
| identical, minus the knee | +0.0199 | stayed up |

Ruled out momentum as the cause: it falls when stepped instantly and
when ramped over 0.2s, 1.0s and 2.0s alike. It is the pose itself, not
how fast it's reached.

### Root cause

`SafetyFilter` pins the **free-floating base** to the settled-standing
reference and only varies joint angles. Probing the knee pose directly:
`l_foot2` rises from z=0.0053 to 0.0103 (a pad silently leaves the
ground) while the CoM moves all of 0.0001m — so the margin stays
comfortably positive.

In reality a bent knee shortens that leg, the pelvis drops and tilts on
that side, and the CoM swings out. Pinning the base makes the check
blind to the dominant effect. For arm motions and *symmetric* hip rolls
the base genuinely barely moves, which is why those predicted correctly
— the approximation only breaks where the pose's whole purpose is to
move the base.

This is the limitation already documented in Phase 1/2 as theoretical
("fine while the robot mimics from a standing position"). It is not
theoretical.

### What has to change

| | Item |
|---|---|
| ✅ | Re-seat the base against each candidate pose instead of pinning it. |
| ✅ | Re-run the dynamics sweep; the knee case flipped to "held back". |
| ⬜ | Only then revisit `ENABLE_LEG_TRACKING`. |

### What was still safe to use meanwhile

The filter stayed enabled by default throughout: strictly better than
the nothing-at-all that preceded it, provably inert on the arms-only
default path, and conservative where it did fire on symmetric leans.
The defect was confined to asymmetric leg poses, which the default
configuration does not generate.

</details>

## Phase 2.6 — ⛔ NOT FIT TO RUN: asymmetric false positives (open, blocks everything)

**`ENABLE_FOLLOW_SAFETY` is DEFAULT OFF as of 2026-09-29.** Two bugs
found in one live session, the second of which invalidates Phase 2.5's
acceptance result.

### Bug 1 — the baseline was not standing (fixed)

`SafetyFilter._apply_stand_keyframe()` reset qpos to the stand keyframe
but **never synced `ctrl`**. `AiNexSimulator._apply_stand_keyframe` does
exactly that, with the comment *"so PD controllers hold the pose rather
than pulling toward zero"* — it wasn't copied. So across the 750-step
settle the position actuators dragged every joint toward **zero**, and
that pose became the filter's reference for "standing": straight knees,
arms at zero, **up to 1.56 rad (89°) from real stand**.

Consequences, all observed live: the gate seeded `current_joints` from
that wrong pose, so every incoming target looked like an enormous move
and was refused (**100% hold rate in the logs** —
`dispatches:12, safety_holds:12`), and at `safe_fraction=0` it commanded
the robot *to* that pose — straightening the knees — toppling it
forward instantly.

Fixed, and guarded by `TestBaselineIsActuallyStanding`. **No test caught
this for two phases** because every other test compared the filter
against its own baseline, so a wrong baseline still looked
self-consistent.

### Bug 2 — the margin is noise for asymmetric poses (OPEN)

With the baseline corrected, checked against real dynamics:

| Pose | Filter | Physics |
|---|---|---|
| `l_ank_roll` 0.05 (2.9°) | −0.0107 UNSAFE | stays up ❌ |
| `r_hip_roll` 0.0625 | −0.0104 UNSAFE | stays up ❌ |
| `r_hip_roll` 0.125 | −0.0214 UNSAFE | stays up ❌ |
| `r_hip_roll` 0.25 | **+0.0378 safe** | stays up ✅ |
| `r_hip_roll` 0.5 | −0.0177 UNSAFE | stays up ❌ |

Unsafe → unsafe → **safe** → unsafe as the angle increases
monotonically. That is not a threshold, it is noise. Along a single
interpolated path the margin reads −0.032 then **+0.038** then −0.015.

**Why Phase 2.5's 12/12 missed it:** every case there was a *symmetric*
leg pose. Those genuinely behave — symmetric hips 0 → −0.35 falls
monotonically 0.0381 → 0.0084 → −1.0 and scales back cleanly to
fraction 0.5. Live mimicry produces *asymmetric* poses almost
exclusively, so the validation set was unrepresentative of the actual
workload.

**Suspected cause** (not yet confirmed): contact-sensor flicker. Real
stand rests on 3 pads (Phase 0). A small asymmetric tilt drops one, so
the support polygon collapses discontinuously — sometimes to under 3
points, returning the −1.0 sentinel. The damped settle fixed ringing
for symmetric poses but not this.

| | Next steps |
|---|---|
| ⬜ | Confirm the flicker hypothesis: log pad-contact counts along an asymmetric sweep and see whether margin jumps coincide with polygon point-count changes. |
| ⬜ | Likely fix: replace binary contact sensors in `get_support_polygon` with a continuous floor-proximity measure. Note the earlier geometric prototype did this and was tolerance-sensitive (worked only 4–8mm), so it needs a principled tolerance — probably derived from contact-force magnitude rather than a distance guess. |
| ⬜ | **Re-validate on an ASYMMETRIC case set.** The symmetric-only set is what let this through. |
| ⬜ | Only then consider re-enabling the default. |

### Lesson worth keeping

Both bugs shared a root: **validating the filter against itself rather
than against ground truth.** The baseline bug survived because tests
were self-consistent; the noise bug survived because the ground-truth
set didn't resemble the real workload. Any future change here should be
checked against stepped dynamics on poses that look like what mimicry
actually generates.

## Phase 2.7 — ⛔ The support-polygon metric is the WRONG TOOL for leg lifts (2026-09-29)

Tested directly against the project's actual goal — lift a leg and stay
balanced. Conclusion: **static CoM-in-support-polygon cannot express
this problem**, regardless of the noise bugs above.

### What the robot can actually do

Left leg lifted by a fraction of a full lift, ramped in over 1.2s, then
held. Ground truth from stepped dynamics:

| Lift | Margin says | Physics |
|---|---|---|
| 0% | +0.0382 | stands, roll +0.6° |
| 10% | −0.0009 | **stands**, roll −0.1° |
| 20% | −0.0009 | **stands**, roll −2.0° |
| 30% | −0.0009 | **stands**, roll −6.9° |
| 40% | −0.0009 | **stands**, roll −14.8° |
| 50% | −0.0010 | **stands**, roll −16.5° |
| 70% | −0.0010 | **stands**, roll −22.2° |
| 100% | −0.0009 | falls, roll −102.5° |

**The robot can already lift its leg ~70% and stay up.** That is a real,
demoable capability that needs no CBF at all.

**And the margin is flat at −0.0009 across the entire range.** It calls
10% (which stands comfortably) exactly as unsafe as 100% (which falls).
It is not merely noisy here — it carries no information at all.

### Why the metric fails in single support

The instant the leg leaves the ground, support collapses to one foot and
the CoM sits ~1mm outside it (measured: CoM 0.0259m from the support
foot centre, foot half-width 0.0250m). That is true at 10% lift and at
100% lift alike, so the margin saturates immediately and stops varying.
Static stability is a yes/no question; how *recoverable* a single-support
pose is, is not.

### Other things ruled out along the way

- **The pose itself is fine.** Placed directly into a full single-leg
  stance with the actuators holding it, the robot drifts only 0.52° →
  −1.99° over 2.8s and keeps its CoM height. It is the *weight transfer*
  that fails, not the destination.
- **Sequencing does not rescue it.** Shifting weight first, then lifting,
  falls the same as doing both together (−106° vs −103°).
- **Support-leg adduction was an artifact.** `r_hip_roll −0.20` appeared
  to swing the support foot 3.5cm inward under the CoM, which looked like
  the answer — but that is base-pinning again. A planted foot has
  friction; hip roll tilts the pelvis instead of translating the foot.
- **The existing ankle/hip balance controller is not enough.** It helps
  measurably (roll −89.6° vs −102.6° and a higher final CoM) but is
  tuned for a few degrees of push recovery with saturation caps, not for
  transferring full body weight onto one foot.

### Where this leaves the approach

| | Option |
|---|---|
| ⚠ | **Option A — shipped, but a leg lift still fell live.** Fixed one real bug in it (below); the remaining cause is unidentified and now instrumented. |
| ✅ | **Bug in the first cap: wrong reference pose.** It scaled toward `_STAND_LEG_TARGETS` (the robot's stand keyframe), but the retargeting's own neutral for a person standing straight is `clamp(0)` — `l_hip_pitch −0.0698, l_knee +0.6737` versus the keyframe's `−0.4887, +0.9250`, **up to 0.42 rad apart**. So the "cap" was bending the robot's legs further whenever a person simply stood still: an offset, not a cap. Now scales toward `retarget_neutral_leg_targets()`, so a motionless person is left untouched at any scale. |
| ✅ | **Also explains the "can't stand straight" wobble.** The retargeted-neutral stance leaves the robot pitched back **8.7°** versus +2.7° at the stand keyframe, and the knee-visibility fallback snaps between the two. Measured: the flicker does *not* topple it (all variants stayed up, peak roll 0.7°), so it is a posture/wobble problem, not the fall. |
| ⬜ | **Fall cause still unknown.** Synthetic landmarks have twice failed to reproduce what live retargeting emits for a leg lift, so the follow heartbeat now logs the actual dispatched `leg_targets` to `logs/clean_logs/`. Read them from a real session rather than guessing a third time. |
| ✅ | **Option A mechanism — DONE 2026-09-29.** `LEG_MIMICRY_SCALE` (default 0.5) performs only part of the way from stand toward each retargeted leg angle, and `ENABLE_LEG_TRACKING` now defaults **on**. Verified against stepped dynamics: a full lift falls (roll −102.5°), the same lift capped stays up (−16.5°); with ±0.25 rad of vision jitter injected, uncapped falls (−104.6°) and capped stays up (−5.8°). Applied in `compute_joint_targets`, so every consumer gets it — follow, capture and `/map-features` alike. Deliberately independent of the stability margin, which Phase 2.7 shows carries no information here. Arms/head are untouched: they barely move this robot's CoM, so capping them would cost fidelity for no safety gain. Tests: `backend/tests/test_leg_mimicry_cap.py` plus two integration tests in `backend/tests/vision/test_pose_to_robot.py`. |
| ⬜ | **The right metric:** replace static CoM-in-polygon with **ZMP / capture point**, which incorporates momentum and *does* vary continuously through single support. This is what the humanoid whole-body-control literature actually uses, and it is the honest technical answer to "lift a leg and stay balanced". Substantially more work. |
| ⬜ | Support-polygon margin remains fine for **double-support** poses (leaning, squatting) and could stay as a guard for those only. |

**Do not invest further in fixing the support-polygon margin for leg
lifts.** The noise bugs in Phase 2.6 are real, but fixing them would
still leave a metric that reads −0.0009 for every lift from 10% to 100%.

## Phase 3 — Real full CBF-QP (if Phase 1's simpler filter isn't sufficient)

| | Item |
|---|---|
| ⬜ | Only pursue if Phase 1's simpler scaling approach proves inadequate — a real optimization-based CBF (needs a QP solver dependency, joint velocity/torque-level formulation) |

## Log

- **2026-09-29 (Phase 2.5)** — **Fixed the false negative: the base is now re-seated against each candidate pose instead of pinned.** Production filter agrees with real dynamics 12/12, including two knee-only cases not previously tested, with no false positives on arm/head poses. Two failed approaches on the way, both worth not repeating: a naive physics settle *rings* (margin non-monotonic; plain standing reads unsafe at 400 steps) — fixed by heavy damping on the shadow model, which is principled since damping changes how fast equilibrium is reached, not where it is; and a hand-rolled geometric re-seat passed all six cases but only inside a 4–8mm floor tolerance window, i.e. a constant tuned to the tests, so it was discarded rather than shipped. **Retracts a Phase 1 conclusion too:** the "genuine mid-motion dip" on ankle roll was not genuine, it was the same pinning artifact in the false-positive direction. Cost rose 1.9ms → 14.8ms per call (4% → 30% of the tick), accepted deliberately.
- **2026-09-29 (later)** — **First real-dynamics test of the filter, and it found a false negative.** Everything through Phase 2 validated with `mj_forward` (kinematics only); this ran actual physics. Good news: the filter's boundary on symmetric leans sits just inside the real one (holds back at 0.30 where physics still copes, catches 0.35/0.45 which genuinely fall) — erring safe. Bad news: the pose it *substitutes* for a rejected leg request falls too, at every ramp rate, because `SafetyFilter` pins the free-floating base — so a bent knee reads as "foot swings up, CoM unchanged, margin fine" when really the pelvis drops and the robot tips. **Retracted the Phase 2 claim that this makes leg tracking safe to enable; it does not.** New Phase 2.5 (base re-seating) now blocks that. Captured as `xfail(strict=True)` so a future fix trips it. Filter stays on by default — still strictly better than the nothing that preceded it, and inert on the arms-only default path.
- **2026-09-29** — Phase 2 done (bar the live visual run): `FollowSafetyGate` wires the Phase 1 filter into the live-follow stream, closing the gap this whole effort was started for — that path previously had no fall/stability check at all. Measured the per-check cost (~1.9 ms vs. a 50 ms tick) before wiring rather than after. Caught a real ordering bug in the wiring during self-review: the gate was being consulted *before* the loop's existing "skip this tick if the previous dispatch is still in flight" check, so a skipped tick would advance the gate's tracked pose to something that was never actually dispatched, leaving it measuring the next frame from a phantom position — moved the filter inside the dispatch branch. Also found the filter never fires on arms-only mimicry (today's default) but does fire on leg motion; see the table above. 16 new tests, 309 passing overall.
- **2026-09-22** — Phase 0 done: `backend/app/balance/cbf.py` (center of mass, support polygon from real contact sensors, signed-distance safety function), 14 tests. Found a real settling-dynamics surprise while writing the tests — true steady-state standing contact is 3 pads, not 4 (`r_foot1` never regains contact, a consequence of the robot's known mass asymmetry) — asserted the real pattern, not an idealized one. Explicit scope: separate from, doesn't touch, the existing ankle/hip controller. Next: Phase 1, the shadow-check safety filter that actually modifies an unsafe target pose.
