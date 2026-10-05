"""Foot pressure: 4 sensors per foot, and where the weight presses.

Step 3 of the real-robot balance plan. The same readings come from the sim
now (sim_foot_pressures, from MuJoCo's contact forces) and from real
pressure pads later, so balance code built on them runs unchanged on both.

Per foot, 4 readings in newtons, in this order:
    front-inner, front-outer, back-inner, back-outer
"inner" is the edge facing the other foot. In the sim the sensors sit at
the corners of the foot's two pads (front pad's front corners, back pad's
back corners) -- where real pads are planned.
"""

from __future__ import annotations

import math

import mujoco
import numpy as np

SENSORS = ("front_inner", "front_outer", "back_inner", "back_outer")
_FLOOR = "floor"


def center_of_pressure(readings: list[float]) -> tuple[float, float, float]:
    """(total load N, inner -1..+1, front -1..+1) for one foot.

    inner: +1 all weight on the inner edge (toward the other foot), -1 on
    the outer edge. front: +1 on the toes, -1 on the heel. NaN when the
    foot carries no load."""
    fi, fo, bi, bo = readings
    load = fi + fo + bi + bo
    if load <= 0:
        return 0.0, math.nan, math.nan
    return load, (fi + bi - fo - bo) / load, (fi + fo - bi - bo) / load


def _foot_frame(model, data, side):
    """Foot origin, rotation, and half-extents (x fore-aft, y across) of the
    combined foot made of its two pads."""
    g1 = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, f"{side}_foot1")
    g2 = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, f"{side}_foot2")
    rot = data.geom_xmat[g1].reshape(3, 3)
    p1, p2 = data.geom_xpos[g1], data.geom_xpos[g2]
    front = (rot.T @ (p1 - p2))[0] + model.geom_size[g1][0]  # front edge, in foot2-centred x
    back = -model.geom_size[g2][0]
    centre = p2 + rot @ np.array([(front + back) / 2, 0.0, 0.0])
    return (g1, g2), centre, rot, (front - back) / 2, model.geom_size[g1][1]


def sim_foot_pressures(model: mujoco.MjModel, data: mujoco.MjData) -> dict[str, list[float]]:
    """Simulated sensor readings for both feet: each foot-floor contact's
    normal force shared between the 4 corner sensors by where it acts
    (bilinear weights), as pads under the corners would feel it."""
    floor = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, _FLOOR)
    out = {}
    f6 = np.zeros(6)
    for side in ("l", "r"):
        pads, centre, rot, half_x, half_y = _foot_frame(model, data, side)
        inner_sign = -1.0 if side == "l" else 1.0  # local +y is the robot's left
        r = [0.0, 0.0, 0.0, 0.0]
        for i in range(data.ncon):
            c = data.contact[i]
            if floor not in (c.geom1, c.geom2) or not ({c.geom1, c.geom2} & set(pads)):
                continue
            mujoco.mj_contactForce(model, data, i, f6)
            fn = abs(f6[0])
            local = rot.T @ (c.pos - centre)
            u = min(1.0, max(0.0, 0.5 + 0.5 * local[0] / half_x))                 # 1 = front
            v = min(1.0, max(0.0, 0.5 + 0.5 * inner_sign * local[1] / half_y))    # 1 = inner
            r[0] += fn * u * v
            r[1] += fn * u * (1 - v)
            r[2] += fn * (1 - u) * v
            r[3] += fn * (1 - u) * (1 - v)
        out[side] = r
    return out
