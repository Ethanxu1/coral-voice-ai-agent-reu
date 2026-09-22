# CBF / Whole-Body Safety Layer — Progress

Tracks a new, **separate** safety layer suggested by the PI: a Control
Barrier Function (CBF) that constrains whatever pose `follow`/mimicry
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
| ⬜ | Safety-filter function: shadow-check a target pose's resulting CoM/support-polygon safety; if unsafe, scale back toward the current pose until safe |
| ⬜ | Unit tests: a pose that's already safe passes through unchanged; a pose that would tip the robot gets scaled back to something safe |
| ⬜ | Live sim test: watch it in the browser viewer, comparable to how the ankle/hip controller was verified |

## Phase 2 — Wire into the live-follow path

| | Item |
|---|---|
| ⬜ | Apply the Phase 1 filter to `follow_controller.py`'s continuous stream, alongside (not replacing) the existing ankle/hip standing-balance loop |
| ⬜ | Compare behavior side-by-side: ankle/hip controller alone vs. CBF safety layer alone vs. both together |

## Phase 3 — Real full CBF-QP (if Phase 1's simpler filter isn't sufficient)

| | Item |
|---|---|
| ⬜ | Only pursue if Phase 1's simpler scaling approach proves inadequate — a real optimization-based CBF (needs a QP solver dependency, joint velocity/torque-level formulation) |

## Log

- **2026-09-22** — Phase 0 done: `backend/app/balance/cbf.py` (center of mass, support polygon from real contact sensors, signed-distance safety function), 14 tests. Found a real settling-dynamics surprise while writing the tests — true steady-state standing contact is 3 pads, not 4 (`r_foot1` never regains contact, a consequence of the robot's known mass asymmetry) — asserted the real pattern, not an idealized one. Explicit scope: separate from, doesn't touch, the existing ankle/hip controller. Next: Phase 1, the shadow-check safety filter that actually modifies an unsafe target pose.
