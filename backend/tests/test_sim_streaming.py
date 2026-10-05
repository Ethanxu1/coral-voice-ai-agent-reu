"""Smooth streamed motion in the simulator (follow mode).

Reported 2026-10-05: in the sim the arms moved very jerkily while following.
SimController.send_commands blocks for the whole move and spawns a thread
per servo, so the follow loop got only ~10-12 updates/s through (log:
~20-24 dispatches per 2 s with as many skips), and each 45 ms move was 2
steps of ~22 ms followed by ~55 ms standing still: move-stop-move.
stream_commands returns at once; one background loop glides every joint to
its newest target, each move lasting until the next one arrives.
"""

from __future__ import annotations

import threading
import time

from app.robot.angle_utils import rad_to_servo_units
from app.robot.interface import ServoCommand
from app.robot.servo_config import SERVO_ID_MAP
from app.robot.sim_controller import SimController

J = "l_sho_pitch"


class FakeSim:
    def __init__(self):
        self.pos = {J: 0.0, "r_sho_pitch": 0.0}
        self.history: list[float] = []
        self.lock = threading.Lock()

    def get_joint_position(self, name):
        with self.lock:
            return self.pos[name]

    def set_joint_position(self, name, value):
        with self.lock:
            self.pos[name] = value
            if name == J:
                self.history.append(value)


def cmd(rad, ms=45, joint=J):
    return [ServoCommand(servo_id=SERVO_ID_MAP[joint], position=rad_to_servo_units(rad), duration_ms=ms)]


def test_stream_returns_at_once():
    ctl = SimController(FakeSim())
    t0 = time.perf_counter()
    ctl.stream_commands(cmd(0.5, ms=500))
    assert time.perf_counter() - t0 < 0.01


def test_streamed_move_glides_in_many_small_steps():
    sim = FakeSim()
    ctl = SimController(sim)
    ctl.stream_commands(cmd(0.5, ms=200))
    time.sleep(0.35)
    values = sim.history
    assert len(values) >= 10, f"only {len(values)} steps"
    assert all(b >= a - 1e-9 for a, b in zip(values, values[1:])), "not monotonic"
    assert abs(values[-1] - 0.5) < 0.01


def test_a_new_target_continues_from_where_the_joint_is():
    """No jump back to the old start, no snap to the new target."""
    sim = FakeSim()
    ctl = SimController(sim)
    ctl.stream_commands(cmd(0.5, ms=300))
    time.sleep(0.15)
    mid = sim.get_joint_position(J)
    assert 0.05 < mid < 0.45
    ctl.stream_commands(cmd(-0.2, ms=300))
    time.sleep(0.03)
    after = sim.get_joint_position(J)
    assert abs(after - mid) < 0.12, (mid, after)


def test_each_move_lasts_until_the_next_command():
    """45 ms moves sent every ~100 ms used to leave the joint idle half the
    time. The streamed move is stretched to cover the gap."""
    sim = FakeSim()
    ctl = SimController(sim)
    ctl.stream_commands(cmd(0.0))
    time.sleep(0.1)
    ctl.stream_commands(cmd(0.3, ms=45))
    time.sleep(0.06)  # longer than 45 ms, shorter than the stretched move
    assert sim.get_joint_position(J) < 0.29


def test_a_blocking_move_cancels_streamed_motion_on_its_joints():
    sim = FakeSim()
    ctl = SimController(sim)
    ctl.stream_commands(cmd(0.5, ms=400))
    time.sleep(0.05)
    ctl.send_commands(cmd(-0.3, ms=40))
    time.sleep(0.15)
    assert abs(sim.get_joint_position(J) + 0.3) < 0.02
