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

## Phase 3 — Real full CBF-QP (if Phase 1's simpler filter isn't sufficient)

| | Item |
|---|---|
| ⬜ | Only pursue if Phase 1's simpler scaling approach proves inadequate — a real optimization-based CBF (needs a QP solver dependency, joint velocity/torque-level formulation) |

## Log

- **2026-09-29 (Phase 2.5)** — **Fixed the false negative: the base is now re-seated against each candidate pose instead of pinned.** Production filter agrees with real dynamics 12/12, including two knee-only cases not previously tested, with no false positives on arm/head poses. Two failed approaches on the way, both worth not repeating: a naive physics settle *rings* (margin non-monotonic; plain standing reads unsafe at 400 steps) — fixed by heavy damping on the shadow model, which is principled since damping changes how fast equilibrium is reached, not where it is; and a hand-rolled geometric re-seat passed all six cases but only inside a 4–8mm floor tolerance window, i.e. a constant tuned to the tests, so it was discarded rather than shipped. **Retracts a Phase 1 conclusion too:** the "genuine mid-motion dip" on ankle roll was not genuine, it was the same pinning artifact in the false-positive direction. Cost rose 1.9ms → 14.8ms per call (4% → 30% of the tick), accepted deliberately.
- **2026-09-29 (later)** — **First real-dynamics test of the filter, and it found a false negative.** Everything through Phase 2 validated with `mj_forward` (kinematics only); this ran actual physics. Good news: the filter's boundary on symmetric leans sits just inside the real one (holds back at 0.30 where physics still copes, catches 0.35/0.45 which genuinely fall) — erring safe. Bad news: the pose it *substitutes* for a rejected leg request falls too, at every ramp rate, because `SafetyFilter` pins the free-floating base — so a bent knee reads as "foot swings up, CoM unchanged, margin fine" when really the pelvis drops and the robot tips. **Retracted the Phase 2 claim that this makes leg tracking safe to enable; it does not.** New Phase 2.5 (base re-seating) now blocks that. Captured as `xfail(strict=True)` so a future fix trips it. Filter stays on by default — still strictly better than the nothing that preceded it, and inert on the arms-only default path.
- **2026-09-29** — Phase 2 done (bar the live visual run): `FollowSafetyGate` wires the Phase 1 filter into the live-follow stream, closing the gap this whole effort was started for — that path previously had no fall/stability check at all. Measured the per-check cost (~1.9 ms vs. a 50 ms tick) before wiring rather than after. Caught a real ordering bug in the wiring during self-review: the gate was being consulted *before* the loop's existing "skip this tick if the previous dispatch is still in flight" check, so a skipped tick would advance the gate's tracked pose to something that was never actually dispatched, leaving it measuring the next frame from a phantom position — moved the filter inside the dispatch branch. Also found the filter never fires on arms-only mimicry (today's default) but does fire on leg motion; see the table above. 16 new tests, 309 passing overall.
- **2026-09-22** — Phase 0 done: `backend/app/balance/cbf.py` (center of mass, support polygon from real contact sensors, signed-distance safety function), 14 tests. Found a real settling-dynamics surprise while writing the tests — true steady-state standing contact is 3 pads, not 4 (`r_foot1` never regains contact, a consequence of the robot's known mass asymmetry) — asserted the real pattern, not an idealized one. Explicit scope: separate from, doesn't touch, the existing ankle/hip controller. Next: Phase 1, the shadow-check safety filter that actually modifies an unsafe target pose.
