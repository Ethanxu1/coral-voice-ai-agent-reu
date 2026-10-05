"""Foot pressure sensing: 4 sensors per foot, simulated now, real later.

Step 3 (docs/cbf-whole-body-progress.md): on one foot the real robot sags
~10 deg, and simulated "soft ankle" models sag for a different reason (the
standing foot rolls onto its inner edge and the lifted foot props it up).
Where the weight presses on each foot, and whether the lifted foot still
carries load, are exactly what foot pressure sensors measure. Sensors are
on order; this layer gives the balance code the same readings from the sim
now and from the real pads later.

Sensor order per foot: front-inner, front-outer, back-inner, back-outer
("inner" = the edge facing the other foot).
"""

from __future__ import annotations

import math

import mujoco
import pytest

from app.balance.foot_pressure import center_of_pressure, sim_foot_pressures


def test_even_pressure_is_centred():
    load, inner, front = center_of_pressure([1.0, 1.0, 1.0, 1.0])
    assert load == pytest.approx(4.0)
    assert inner == pytest.approx(0.0) and front == pytest.approx(0.0)


def test_weight_on_the_inner_edge_reads_plus_one():
    load, inner, front = center_of_pressure([2.0, 0.0, 2.0, 0.0])
    assert inner == pytest.approx(1.0) and front == pytest.approx(0.0)


def test_weight_on_the_heel_reads_minus_one_front():
    _, _, front = center_of_pressure([0.0, 0.0, 3.0, 3.0])
    assert front == pytest.approx(-1.0)


def test_no_load_has_no_centre():
    load, inner, front = center_of_pressure([0.0, 0.0, 0.0, 0.0])
    assert load == 0.0 and math.isnan(inner) and math.isnan(front)


def _standing_sim():
    from app.simulator.mujoco_sim import AiNexSimulator

    sim = AiNexSimulator(servo_model="stiff")
    for _ in range(1500):
        mujoco.mj_step(sim.model, sim.data)
    return sim


def test_sim_standing_robot_puts_its_weight_on_both_feet():
    sim = _standing_sim()
    p = sim_foot_pressures(sim.model, sim.data)
    weight = sum(sim.model.body_mass) * 9.81
    total = sum(p["l"]) + sum(p["r"])
    assert total == pytest.approx(weight, rel=0.1)
    assert min(sum(p["l"]), sum(p["r"])) > 0.25 * weight


def test_sim_lift_moves_the_weight_onto_the_standing_foot_centred():
    """Stiff sim, left leg held up: all weight on the right foot, pressing
    near its middle, and none on the lifted foot."""
    import app.vision.leg_lift_controller as llc
    from app.robot.leg_lift_check import DT, _person

    sim = _standing_sim()
    ctl = llc.LegLiftController()
    for f in [0.0] * 10 + [0.2 * (k + 1) / 12 for k in range(12)] + [0.2] * 30:
        out = ctl.update(_person("l", f), DT)
        for j in llc.LEG_JOINTS + llc.ANKLES:
            sim.set_joint_position(j, out[j])
        for _ in range(25):
            mujoco.mj_step(sim.model, sim.data)
    p = sim_foot_pressures(sim.model, sim.data)
    assert sum(p["l"]) < 0.5
    load, inner, _ = center_of_pressure(p["r"])
    assert load > 20.0
    assert abs(inner) < 0.3
