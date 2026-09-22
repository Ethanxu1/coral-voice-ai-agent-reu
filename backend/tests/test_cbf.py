"""Tests for the whole-body stability geometry (backend/app/balance/cbf.py).

Two groups, deliberately separated:
  - Pure geometry (_convex_hull_2d, signed_distance_to_polygon): plain
    coordinate lists, no MuJoCo, fast and fully deterministic -- these
    prove the MATH is right in isolation.
  - Real-model integration (get_center_of_mass, get_support_polygon,
    stability_margin): the actual AiNex model, matching this project's
    established pattern of testing sim-facing code against the real
    model rather than a mock.

Deliberately NOT tested here: a real one-foot-lifted stance. Getting the
robot to actually, stably balance on one foot is Phase 5 of the main
balance effort, not something to fake as unit-test setup -- these tests
only need a state where fewer than four pads are in contact to prove
the CODE handles it, and "before any physics stepping" already gives
that state for free (contact sensors read zero until real dynamics has
run), without needing a real single-leg stance.
"""

from __future__ import annotations

import math

import mujoco
import pytest

import app.resource_path as resource_path
from app.balance.cbf import (
    _convex_hull_2d,
    foot_pad_in_contact,
    get_center_of_mass,
    get_support_polygon,
    signed_distance_to_polygon,
    stability_margin,
)

_MODEL_PATH = str(resource_path.repo_root() / "assets" / "ainex" / "ainex.xml")
_UNIT_SQUARE = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]


class TestConvexHull:
    def test_square_input_returns_all_four_corners_ccw(self):
        # Fed out of order on purpose -- the hull shouldn't care about input order.
        hull = _convex_hull_2d([(1.0, 1.0), (0.0, 0.0), (1.0, 0.0), (0.0, 1.0)])
        assert set(hull) == set(_UNIT_SQUARE)
        # Counter-clockwise: consecutive cross products all positive.
        n = len(hull)
        for i in range(n):
            a, b, c = hull[i], hull[(i + 1) % n], hull[(i + 2) % n]
            cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
            assert cross > 0

    def test_interior_point_is_dropped_from_the_hull(self):
        hull = _convex_hull_2d([*_UNIT_SQUARE, (0.5, 0.5)])
        assert (0.5, 0.5) not in hull
        assert len(hull) == 4

    def test_duplicate_points_are_deduplicated(self):
        hull = _convex_hull_2d([*_UNIT_SQUARE, *_UNIT_SQUARE])
        assert len(hull) == 4


class TestSignedDistance:
    def test_center_of_square_is_positive_and_correct_magnitude(self):
        # Unit square, center is 0.5 from every edge.
        assert signed_distance_to_polygon((0.5, 0.5), _UNIT_SQUARE) == pytest.approx(0.5)

    def test_point_outside_is_negative(self):
        assert signed_distance_to_polygon((2.0, 0.5), _UNIT_SQUARE) == pytest.approx(-1.0)

    def test_point_on_edge_is_approximately_zero(self):
        assert signed_distance_to_polygon((0.5, 0.0), _UNIT_SQUARE) == pytest.approx(0.0, abs=1e-9)

    def test_fewer_than_three_points_returns_the_unsafe_sentinel(self):
        assert signed_distance_to_polygon((0.0, 0.0), []) < 0
        assert signed_distance_to_polygon((0.0, 0.0), [(1.0, 1.0)]) < 0
        assert signed_distance_to_polygon((0.0, 0.0), [(1.0, 1.0), (2.0, 2.0)]) < 0


@pytest.fixture(scope="module")
def model() -> mujoco.MjModel:
    return mujoco.MjModel.from_xml_path(_MODEL_PATH)


def _fresh_keyframe_data(model: mujoco.MjModel) -> mujoco.MjData:
    """Stand keyframe applied, but NOT stepped -- contact sensors read
    zero in this state (confirmed empirically), which is exactly the
    "nothing touching yet" case some tests below need."""
    data = mujoco.MjData(model)
    key_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_KEY, "stand")
    mujoco.mj_resetDataKeyframe(model, data, key_id)
    return data


def _settled_stand_data(model: mujoco.MjModel, steps: int = 750) -> mujoco.MjData:
    """Stand keyframe, then actually stepped under real physics so
    contact sensors populate and the pose has settled onto the floor.

    750 steps (1.5s at this model's 0.002s timestep) — found empirically,
    not guessed: the settled *pattern* of which pads are in contact keeps
    changing for a surprisingly long time (still shifting at 400+ steps),
    only becoming stable and repeatable from ~750 steps onward (confirmed
    out to 2000 steps with no further change)."""
    data = _fresh_keyframe_data(model)
    for _ in range(steps):
        mujoco.mj_step(model, data)
    return data


class TestRealModelBeforeAnyPhysicsStepping:
    """A freshly-reset keyframe has no evaluated contacts yet -- this is
    the "no support" edge case, obtained for free rather than engineered."""

    def test_no_foot_pad_reports_contact(self, model):
        data = _fresh_keyframe_data(model)
        for pad in ("l_foot1", "l_foot2", "r_foot1", "r_foot2"):
            assert foot_pad_in_contact(model, data, pad) is False

    def test_support_polygon_is_empty(self, model):
        data = _fresh_keyframe_data(model)
        assert get_support_polygon(model, data) == []

    def test_stability_margin_is_the_unsafe_sentinel(self, model):
        data = _fresh_keyframe_data(model)
        assert stability_margin(model, data) < 0


class TestRealModelStandingSettled:
    def test_three_of_four_pads_report_contact_not_all_four(self, model):
        """Found empirically, not assumed: in true settled steady state,
        r_foot1 (the right foot's larger, front pad) never regains
        contact -- a real consequence of this robot's known right-side-
        heavy mass asymmetry (independently confirmed by weighing the
        physical robot -- see docs/balance-controller-progress.md Phase
        2), not a bug in the sensor or this code. The support base this
        robot actually stands on is smaller than "both feet fully flat"
        would suggest, and a real safety function needs to reflect that,
        not an idealized assumption."""
        data = _settled_stand_data(model)
        assert foot_pad_in_contact(model, data, "l_foot1") is True
        assert foot_pad_in_contact(model, data, "l_foot2") is True
        assert foot_pad_in_contact(model, data, "r_foot1") is False
        assert foot_pad_in_contact(model, data, "r_foot2") is True

    def test_center_of_mass_is_roughly_centered_over_the_feet(self, model):
        data = _settled_stand_data(model)
        com_x, com_y, com_z = get_center_of_mass(data)
        # Feet are ~3cm either side of the midline (see ainex.xml foot
        # body positions) -- a genuinely standing robot's CoM should be
        # within a few cm of that midline, not off in the next room.
        assert abs(com_x) < 0.05
        assert abs(com_y) < 0.05
        assert com_z > 0.1  # sanity: the robot is upright, not collapsed

    def test_support_polygon_is_a_real_non_degenerate_shape(self, model):
        data = _settled_stand_data(model)
        polygon = get_support_polygon(model, data)
        # 3 contacting pads (see the test above) x 4 corners = 12 input
        # points, collapsing via the convex hull -- assert a real,
        # non-degenerate polygon, not an exact count (that's an
        # implementation detail of this specific geometry; the
        # interior-point-gets-dropped behavior is already covered above).
        assert len(polygon) >= 4

    def test_stability_margin_is_positive_when_standing_normally(self, model):
        data = _settled_stand_data(model)
        margin = stability_margin(model, data)
        assert margin > 0
        # Sanity bound: this robot's feet are only a few cm across: a
        # multi-meter margin would mean the polygon/CoM math is off by
        # orders of magnitude, not a real result.
        assert margin < 0.2
