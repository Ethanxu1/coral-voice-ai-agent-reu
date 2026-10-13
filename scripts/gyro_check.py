"""Which gyro axis is "turning", and which sign is "turning left"?

Needs the robot server running (it serves GET /imu). With the robot standing
(torque on), run this, keep the robot still for the first 2 s, then turn it
by hand like a turntable about a QUARTER TURN (90 deg) TO THE ROBOT'S OWN
LEFT, and hold it still until the end:

    .venv/bin/python scripts/gyro_check.py
    .venv/bin/python scripts/gyro_check.py --ip 192.168.8.219 --seconds 10

It integrates each gyro axis (bias from the still start removed) and prints
the totals. The turning axis reads about +-90; its sign says which way is
positive. Tell Claude the result: it sets YAW_GYRO_AXIS / YAW_GYRO_SIGN in
backend/app/robot/pi/nodes/walking.py.
"""

from __future__ import annotations

import argparse
import sys
import time

import httpx

STILL_S = 2.0


def main(ip: str, seconds: float) -> None:
    url = f"http://{ip}:9000/imu"
    samples: list[tuple[float, list[float]]] = []
    t0 = time.monotonic()
    print("Keep it still...", flush=True)
    announced = False
    with httpx.Client(timeout=1.0) as client:
        while (now := time.monotonic() - t0) < seconds:
            try:
                values = client.get(url).json().get("values")
            except Exception as e:
                sys.exit(f"Can't read {url}: {e}. Is the robot server running the new server.py?")
            if values and len(values) >= 6:
                samples.append((now, [float(v) for v in values[3:6]]))
            if now >= STILL_S and not announced:
                print("NOW turn it ~90 deg to the ROBOT'S LEFT, then hold still.", flush=True)
                announced = True
    still = [g for t, g in samples if t < STILL_S - 0.2]
    if len(still) < 3 or len(samples) < 10:
        sys.exit(f"Too few readings ({len(samples)}); check the connection and try again.")
    bias = [sum(g[i] for g in still) / len(still) for i in range(3)]
    total = [0.0, 0.0, 0.0]
    for (t_a, g_a), (t_b, g_b) in zip(samples, samples[1:]):
        if t_a < STILL_S - 0.2:
            continue
        for i in range(3):
            total[i] += ((g_a[i] + g_b[i]) / 2 - bias[i]) * (t_b - t_a)
    rate = len(samples) / seconds
    print(f"\n{len(samples)} readings ({rate:.0f}/s). Turned (deg): "
          f"gyro x {total[0]:+.0f}   gyro y {total[1]:+.0f}   gyro z {total[2]:+.0f}")
    axis = max(range(3), key=lambda i: abs(total[i]))
    print(f"Turning axis: gyro {'xyz'[axis]} (YAW_GYRO_AXIS = {axis}), "
          f"left turn reads {'positive' if total[axis] > 0 else 'negative'} "
          f"(YAW_GYRO_SIGN = {1.0 if total[axis] > 0 else -1.0})")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--ip", default="192.168.8.219")
    p.add_argument("--seconds", type=float, default=8.0)
    a = p.parse_args()
    main(a.ip, a.seconds)
