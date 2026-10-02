"""On the real robot, follow mode must not move the legs (yet).

2026-10-02: arms-only follow on the robot; the camera lost the person's legs
for 60-78% of frames and the readings it did get said a leg was raised
(0.74, 1.0). The leg-lift controller slid the hips and started a lift, and
on the real robot one-foot stance sags ~10 deg (Phase 2.17) -- it tipped
over. Until hardware leg balance works, legs and ankles hold stand whenever
follow drives the real robot. The sim keeps full leg mimicry.
"""

from __future__ import annotations

import pytest

from app import config
from app.follow_controller import legs_follow_person, pin_legs_to_stand
from app.state import state
from app.vision.leg_lift_controller import ANKLES, LEG_JOINTS, _stand


@pytest.mark.parametrize("mode,sim_only,expected", [
    ("robot", None, False),     # follow on the real robot
    ("robot", False, False),
    ("robot", True, True),      # sim-only toggle: robot untouched
    ("sim", None, True),
])
def test_legs_follow_the_person_only_when_the_real_robot_is_not_driven(
        monkeypatch, mode, sim_only, expected):
    monkeypatch.setattr(state, "robot_mode", mode)
    monkeypatch.setattr(config, "HARDWARE_LEG_MIMICRY", False)
    assert legs_follow_person(sim_only) is expected


def test_hardware_leg_mimicry_can_be_switched_back_on_deliberately(monkeypatch):
    monkeypatch.setattr(state, "robot_mode", "robot")
    monkeypatch.setattr(config, "HARDWARE_LEG_MIMICRY", True)
    assert legs_follow_person(None) is True


def test_pinning_holds_every_leg_and_ankle_joint_at_stand_and_leaves_arms():
    targets = {j: _stand(j) + 0.4 for j in LEG_JOINTS + ANKLES}
    targets["l_sho_pitch"] = 0.7
    pinned = pin_legs_to_stand(targets)
    for j in LEG_JOINTS + ANKLES:
        assert pinned[j] == pytest.approx(_stand(j)), j
    assert pinned["l_sho_pitch"] == 0.7


def test_pinning_fills_in_legs_the_camera_did_not_report():
    pinned = pin_legs_to_stand({"l_sho_pitch": 0.7})
    assert set(LEG_JOINTS + ANKLES) <= set(pinned)
