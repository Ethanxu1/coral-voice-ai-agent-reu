"""Tests for wait_until_arrived (POST /set-pose's Dance Game option)."""

from __future__ import annotations

import asyncio
import time

from app.services import motion


class _StuckSim:
    """A joint held short of its target (out of reach, or gravity wins)."""

    def get_actual_joint_positions(self, joint_names):
        return {name: 0.5 for name in joint_names}


def test_a_joint_that_stops_short_does_not_stall_the_caller():
    """Some poses can't be fully reached; once the joint stops moving the wait
    must end, rather than holding the next dance move until the timeout."""
    start = time.monotonic()
    asyncio.run(motion.wait_until_arrived(_StuckSim(), {"l_sho_pitch": 1.5}))
    assert time.monotonic() - start < motion.ARRIVAL_TIMEOUT_S / 2
