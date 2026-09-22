"""Whole-body stability geometry — the foundation for a CBF-style safety
layer around mimicry (docs/cbf-whole-body-progress.md).

Deliberately separate from, and does not touch, the existing ankle/hip
standing-balance controller (controller.py) — that stays as the tested,
working fallback. This module answers a different, whole-body question
that controller.py's single torso-tilt reading can't: given where the
robot's mass actually is right now, and which feet are actually touching
the ground, is it statically stable?

Why this needs to be fast, unlike StabilityChecker
(backend/app/collision/stability_checker.py): that module answers "would
this pose make the robot fall" by running a ~2.5 second physics rollout
per check — fine for a one-time check before a discrete pose, useless for
checking every frame of continuous real-time mimicry (which is exactly
why the live-follow path currently has no fall check applied to it at
all — see docs/balance-controller-progress.md Phase 4). Center of mass
vs. support polygon is a direct, instantaneous read of MuJoCo's own
physics state — no rollout needed, cheap enough for a per-frame safety
filter.

Two geoms per foot (see assets/ainex/ainex.xml): l_foot1/l_foot2 and
r_foot1/r_foot2, each a flat box rigidly attached to that leg's ankle-roll
body. The model already defines floor-contact sensors for all four
(l_foot1_floor_found, etc.) — a nonzero reading means that pad is
currently touching the ground. The "support polygon" is the convex hull
of whichever pads are actually in contact right now, not a fixed
assumption that both feet are always down (this is deliberately built to
also work standing on one foot, ahead of Phase 5 of the main balance
effort).
"""

from __future__ import annotations

import mujoco

# geom name -> its floor-contact sensor name, one pair per foot pad.
_FOOT_PADS: dict[str, str] = {
    "l_foot1": "l_foot1_floor_found",
    "l_foot2": "l_foot2_floor_found",
    "r_foot1": "r_foot1_floor_found",
    "r_foot2": "r_foot2_floor_found",
}


def _sensor_value(model: mujoco.MjModel, data: mujoco.MjData, name: str) -> float:
    sid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SENSOR, name)
    if sid < 0:
        raise ValueError(f"sensor '{name}' not found in model")
    adr = int(model.sensor_adr[sid])
    return float(data.sensordata[adr])


def get_center_of_mass(data: mujoco.MjData) -> tuple[float, float, float]:
    """Whole-robot center of mass, in world coordinates. `subtree_com[0]`
    is MuJoCo's own built-in quantity for the subtree rooted at the world
    body — i.e. the entire model — so no manual mass-weighted average is
    needed here."""
    com = data.subtree_com[0]
    return float(com[0]), float(com[1]), float(com[2])


def foot_pad_in_contact(model: mujoco.MjModel, data: mujoco.MjData, pad_geom_name: str) -> bool:
    """Whether one specific foot pad (e.g. "l_foot1") is currently
    touching the ground, per its floor-contact sensor. Caller must have
    already stepped physics at least once (mj_step, not just mj_forward)
    — contact sensors read zero until real dynamics has run; a fresh
    keyframe reset with no stepping reads every pad as not-in-contact."""
    sensor_name = _FOOT_PADS.get(pad_geom_name)
    if sensor_name is None:
        raise ValueError(f"'{pad_geom_name}' is not a known foot pad geom")
    return _sensor_value(model, data, sensor_name) > 0.0


def _pad_world_corners(model: mujoco.MjModel, data: mujoco.MjData, geom_name: str) -> list[tuple[float, float]]:
    """The four ground-projected (x, y) corners of one flat box foot pad,
    in world coordinates — the geom's world position/orientation applied
    to its known local half-extents (model.geom_size)."""
    gid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, geom_name)
    if gid < 0:
        raise ValueError(f"geom '{geom_name}' not found in model")
    half_x, half_y, _half_z = model.geom_size[gid]
    center = data.geom_xpos[gid]
    rot = data.geom_xmat[gid].reshape(3, 3)
    corners = []
    for sx in (half_x, -half_x):
        for sy in (half_y, -half_y):
            local = (sx, sy, 0.0)
            world = center + rot @ local
            corners.append((float(world[0]), float(world[1])))
    return corners


def _convex_hull_2d(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Andrew's monotone chain — a small, dependency-free 2D convex hull.
    Returns hull vertices in counter-clockwise order, deduplicated.
    Support-polygon inputs here are at most 8 points (two feet x four
    corners), so an O(n log n) textbook algorithm is more than enough;
    not worth an external dependency (scipy is present in this
    environment but isn't an explicit project dependency)."""
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper: list[tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    return lower[:-1] + upper[:-1]


def get_support_polygon(model: mujoco.MjModel, data: mujoco.MjData) -> list[tuple[float, float]]:
    """Convex hull of whichever foot pads are currently touching the
    ground. Empty list means no support at all (airborne or a sensor
    problem) — callers must treat that as unsafe, not a valid polygon
    with a distance to measure against."""
    corners: list[tuple[float, float]] = []
    for geom_name in _FOOT_PADS:
        if foot_pad_in_contact(model, data, geom_name):
            corners.extend(_pad_world_corners(model, data, geom_name))
    if not corners:
        return []
    return _convex_hull_2d(corners)


def signed_distance_to_polygon(point: tuple[float, float], polygon: list[tuple[float, float]]) -> float:
    """The CBF safety function h(x): positive when `point` is inside
    `polygon` (with that value being roughly the safety margin, in
    meters, to the nearest edge), negative when outside (unsafe — gravity
    will tip the robot over the edge it crossed). `polygon` must be
    counter-clockwise (get_support_polygon's own output already is).

    Degenerate inputs (fewer than 3 points — e.g. only one pad in
    contact, or none) can't form a real polygon; returns a large
    negative number rather than raising, since "not enough support" is
    itself a real, meaningful unsafe result a caller should be able to
    act on without a special case.
    """
    if len(polygon) < 3:
        return -1.0  # 1 meter "unsafe" -- far larger than this robot's own scale

    n = len(polygon)
    min_dist = float("inf")
    for i in range(n):
        p1 = polygon[i]
        p2 = polygon[(i + 1) % n]
        edge = (p2[0] - p1[0], p2[1] - p1[1])
        edge_len = (edge[0] ** 2 + edge[1] ** 2) ** 0.5
        if edge_len == 0.0:
            continue
        # Left-hand normal of a CCW edge points outward... no: for a CCW
        # polygon, the INTERIOR is to the LEFT of each directed edge, so
        # the left-hand normal (-dy, dx) points INWARD. Signed distance
        # via that normal is positive when `point` is on the interior
        # side, which is exactly the sign convention this function
        # promises.
        normal = (-edge[1] / edge_len, edge[0] / edge_len)
        to_point = (point[0] - p1[0], point[1] - p1[1])
        dist = to_point[0] * normal[0] + to_point[1] * normal[1]
        min_dist = min(min_dist, dist)
    return min_dist


def stability_margin(model: mujoco.MjModel, data: mujoco.MjData) -> float:
    """The actual CBF h(x) for the live robot right now: signed distance
    from the center of mass's ground projection to the current support
    polygon. Positive = statically stable with that much margin (meters);
    negative = already outside the base of support, tipping over.
    Combines get_center_of_mass + get_support_polygon +
    signed_distance_to_polygon — the one function most callers need."""
    com_x, com_y, _com_z = get_center_of_mass(data)
    polygon = get_support_polygon(model, data)
    return signed_distance_to_polygon((com_x, com_y), polygon)
