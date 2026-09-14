"""Standing-balance background loop, wired to the LIVE MuJoCo simulator.

Lets BalanceController's correction be watched in the browser's 3D
viewer (/ws/sim) before ever touching the real robot — the visual half
of Phase 1's sim closed-loop verification that a blind headless script
couldn't resolve (docs/balance-controller-progress.md): watching it
happen with a push you control should succeed where a script that just
printed numbers didn't.

Roll only, matching balance_loop.py's Pi-side scope. Not because sim has
the same unverified-axis problem the real IMU does — sim_source.py's
convention is independently confirmed by rotating the actual model — but
to keep this loop's behavior directly comparable to the Pi one once
pitch is eventually confirmed there too, rather than sim and hardware
diverging in what they correct.

Off by default. Does not run, and does not affect the simulator, unless
POST /balance/start is called.
"""

from __future__ import annotations

import threading
import time

from app.balance.controller import BalanceController, BalanceGains, apply_balance_offset
from app.balance.sim_source import read_attitude
from app.simulator import AiNexSimulator

_ROLL_JOINTS: tuple[str, ...] = ("l_ank_roll", "r_ank_roll", "l_hip_roll", "r_hip_roll")

# Sim has no body-service blocking floor like the Pi's version does — 50 Hz
# (the same ceiling the plan treats as the servo bus's real-hardware max)
# is genuinely achievable here, so this tick rate is actually representative
# of what the Pi loop is reaching for, not just a nominal sim-only number.
_TICK_SECONDS = 0.02


class SimBalanceLoop:
    """Background thread running BalanceController's roll channels against
    the live simulator's own attitude sensors. OFF by default."""

    def __init__(self, simulator: AiNexSimulator, gains: BalanceGains | None = None):
        self._simulator = simulator
        self._controller = BalanceController(gains)
        # stand's roll joints are all at their centered pulse (0 rad) — same
        # reasoning as balance_loop.py's Pi-side baseline.
        self._baseline_rad: dict[str, float] = {j: 0.0 for j in _ROLL_JOINTS}
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._last_tick_t: float | None = None
        self.last_error: str | None = None
        self.tick_count = 0

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._controller.reset()
        self._last_tick_t = None
        self.last_error = None
        self.tick_count = 0
        self._thread = threading.Thread(target=self._run, name="sim-balance-loop", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None

    def _run(self) -> None:
        while not self._stop_event.is_set():
            tick_start = time.monotonic()
            try:
                self._tick()
                self.tick_count += 1
            except Exception as e:  # noqa: BLE001 — a bad tick must not kill the loop silently
                self.last_error = str(e)
            elapsed = time.monotonic() - tick_start
            time.sleep(max(0.0, _TICK_SECONDS - elapsed))

    def _tick(self) -> None:
        now = time.monotonic()
        dt = _TICK_SECONDS if self._last_tick_t is None else max(1e-3, now - self._last_tick_t)
        self._last_tick_t = now

        attitude = read_attitude(self._simulator.model, self._simulator.data)
        offset = self._controller.update(attitude, dt)
        roll_offset = {j: offset[j] for j in _ROLL_JOINTS}

        corrected = apply_balance_offset(self._baseline_rad, roll_offset)
        for joint, rad in corrected.items():
            self._simulator.set_joint_position(joint, rad)
