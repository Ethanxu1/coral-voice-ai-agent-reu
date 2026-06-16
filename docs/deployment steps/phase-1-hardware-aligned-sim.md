# Phase 1: Hardware-Aligned Simulator

**Goal:** Restructure how the codebase communicates with the robot so it mirrors the physical AiNex hardware's interface — servo IDs, integer angle encoding, time-based motion commands, feedback structures — while still rendering in MuJoCo. After this phase, the MuJoCo simulator becomes a backend behind a hardware abstraction layer (HAL), and the physical transition in Phase 2 becomes a matter of swapping the backend.

---

## Overview of Changes

| Area | Current State | Target State |
|------|--------------|-------------|
| Command unit | Radians (float) | 0–1000 integer (Hiwonder scale, 0–240°) |
| Command type | `set_joint_position(name, rad)` | `ServoCommand(id, position, duration_ms)` |
| Joint addressing | String name (`"head_pan"`) | Integer servo ID (e.g. `1`) + name lookup |
| Timing | Implicit (MuJoCo PD controller) | Explicit duration in milliseconds per move |
| Speed parameter | Abstract multiplier (1.0–5.0) | Converted to `duration_ms` (e.g. 500–3000ms) |
| Feedback | `data.ctrl[i]` (instantaneous) | `ServoFeedback(id, position, temperature, voltage)` |
| Architecture | Direct calls into `AiNexSimulator` | `RobotController` interface, sim is one backend |

---

## Step 1 — Define the Hardware Abstraction Layer (HAL)

Create `src/coral_agent/robot/interface.py`.

Define the data types and abstract base class that both the simulator and hardware backends will implement:

```python
from dataclasses import dataclass
from abc import ABC, abstractmethod

@dataclass
class ServoCommand:
    servo_id: int
    position: int        # Hiwonder scale: 0–1000 (maps to 0–240°)
    duration_ms: int     # Movement time in milliseconds (0–30000)

@dataclass
class ServoFeedback:
    servo_id: int
    position: int        # 0–1000
    temperature: int     # Celsius (physical robot: warn >50°C)
    voltage: int         # millivolts (physical robot: warn <9000mV)

class RobotController(ABC):
    @abstractmethod
    def send_commands(self, commands: list[ServoCommand]) -> None: ...

    @abstractmethod
    def read_feedback(self, servo_ids: list[int]) -> list[ServoFeedback]: ...

    @abstractmethod
    def reset_to_stand(self) -> None: ...

    @abstractmethod
    def get_joint_positions(self) -> dict[str, int]: ...  # returns 0-1000 scale
```

---

## Step 2 — Create the Servo ID Configuration

Create `src/coral_agent/robot/servo_config.py`.

Map every joint name to the physical AiNex servo ID. These IDs must match the IDs burned into the physical servo hardware. Verify against the AiNex documentation / `hiwonder_servo_controller` examples before physical deployment.

```python
# Joint name → Hiwonder servo ID
# IDs 1–24 match the AiNex RPi 5 wiring diagram
SERVO_ID_MAP: dict[str, int] = {
    # Head (2 servos)
    "head_pan":     1,
    "head_tilt":    2,
    # Right arm (5 servos)
    "r_sho_pitch":  3,
    "r_sho_roll":   4,
    "r_el_pitch":   5,
    "r_el_yaw":     6,
    "r_gripper":    7,
    # Left arm (5 servos)
    "l_sho_pitch":  8,
    "l_sho_roll":   9,
    "l_el_pitch":   10,
    "l_el_yaw":     11,
    "l_gripper":    12,
    # Right leg (6 servos)
    "r_hip_yaw":    13,
    "r_hip_roll":   14,
    "r_hip_pitch":  15,
    "r_knee":       16,
    "r_ank_pitch":  17,
    "r_ank_roll":   18,
    # Left leg (6 servos)
    "l_hip_yaw":    19,
    "l_hip_roll":   20,
    "l_hip_pitch":  21,
    "l_knee":       22,
    "l_ank_pitch":  23,
    "l_ank_roll":   24,
}

# Reverse map: servo ID → joint name
JOINT_NAME_MAP: dict[int, str] = {v: k for k, v in SERVO_ID_MAP.items()}
```

> **Note:** The exact servo IDs above are placeholders. They must be confirmed against the physical robot's wiring before Phase 2. The AiNex documentation's "Robot Hardware Structure" lesson describes the servo numbering convention.

---

## Step 3 — Build Angle Conversion Utilities

Create `src/coral_agent/robot/angle_utils.py`.

The physical robot uses integers 0–1000 to represent 0°–240°. The simulator uses radians. All conversion must pass through this single module to avoid drift.

```python
import math

# Hiwonder servo: 1000 units = 240 degrees
UNITS_PER_DEGREE = 1000 / 240      # ≈ 4.167
DEGREES_PER_UNIT = 240 / 1000      # = 0.24°
CENTER_UNITS = 500                   # 500 = 120° = physical center/neutral

def rad_to_servo_units(rad: float) -> int:
    """Convert radians (signed, centered at 0) to Hiwonder servo units (0–1000)."""
    degrees = math.degrees(rad)
    # Physical center is 120° (500 units); radians 0 maps to center
    units = CENTER_UNITS + round(degrees * UNITS_PER_DEGREE)
    return max(0, min(1000, units))

def servo_units_to_rad(units: int) -> float:
    """Convert Hiwonder servo units (0–1000) back to signed radians."""
    degrees = (units - CENTER_UNITS) * DEGREES_PER_UNIT
    return math.radians(degrees)

def speed_to_duration_ms(speed: float) -> int:
    """Convert the abstract speed multiplier (0.1–5.0) to a move duration.

    speed=1.0 → 1000ms (moderate)
    speed=5.0 → 200ms  (fast)
    speed=0.1 → 5000ms (very slow)
    """
    return max(200, min(5000, round(1000 / speed)))
```

---

## Step 4 — Implement the Simulator Backend

Create `src/coral_agent/robot/sim_controller.py`.

This wraps the existing `AiNexSimulator` and implements `RobotController`. Critically, it accepts `ServoCommand` objects (integer units + duration) and converts them back to MuJoCo internally. It also simulates time-based motion by interpolating the MuJoCo target over `duration_ms` rather than setting it instantly.

```python
import threading
import time
from coral_agent.robot.interface import RobotController, ServoCommand, ServoFeedback
from coral_agent.robot.servo_config import SERVO_ID_MAP, JOINT_NAME_MAP
from coral_agent.robot.angle_utils import rad_to_servo_units, servo_units_to_rad
from coral_agent.simulator.mujoco_sim import AiNexSimulator

class SimController(RobotController):
    def __init__(self, simulator: AiNexSimulator):
        self._sim = simulator

    def send_commands(self, commands: list[ServoCommand]) -> None:
        """Dispatch servo commands to the MuJoCo simulator.

        Spawns a thread per command to simulate concurrent timed motion,
        mirroring how the physical bus processes multi-servo move commands.
        """
        threads = []
        for cmd in commands:
            joint_name = JOINT_NAME_MAP.get(cmd.servo_id)
            if joint_name is None:
                continue
            t = threading.Thread(
                target=self._interpolate_joint,
                args=(joint_name, cmd.position, cmd.duration_ms),
                daemon=True,
            )
            threads.append(t)
        for t in threads:
            t.start()
        # Wait for all joints to finish before returning
        for t in threads:
            t.join()

    def _interpolate_joint(self, joint_name: str, target_units: int, duration_ms: int) -> None:
        """Smoothly move a joint from current position to target over duration_ms."""
        target_rad = servo_units_to_rad(target_units)
        start_rad = self._sim.get_joint_position(joint_name)
        steps = max(1, duration_ms // 20)  # update every 20ms
        for i in range(1, steps + 1):
            t = i / steps
            interpolated = start_rad + t * (target_rad - start_rad)
            self._sim.set_joint_position(joint_name, interpolated)
            time.sleep(0.02)

    def read_feedback(self, servo_ids: list[int]) -> list[ServoFeedback]:
        """Return simulated feedback. Temperature and voltage are nominal constants."""
        feedback = []
        for servo_id in servo_ids:
            joint_name = JOINT_NAME_MAP.get(servo_id)
            if joint_name is None:
                continue
            rad = self._sim.get_joint_position(joint_name)
            feedback.append(ServoFeedback(
                servo_id=servo_id,
                position=rad_to_servo_units(rad),
                temperature=35,    # nominal safe temperature
                voltage=11100,     # nominal full battery (11.1V in mV)
            ))
        return feedback

    def reset_to_stand(self) -> None:
        self._sim.reset_pose()

    def get_joint_positions(self) -> dict[str, int]:
        states = self._sim.get_all_joint_states()
        return {
            joint: rad_to_servo_units(rad)
            for joint, rad in states.items()
        }
```

---

## Step 5 — Update Primitives to Emit ServoCommands

Modify `src/coral_agent/primitives.py` to add a new output function. The existing `resolve_primitive()` stays unchanged for backward compatibility. Add alongside it:

```python
from coral_agent.robot.interface import ServoCommand
from coral_agent.robot.servo_config import SERVO_ID_MAP
from coral_agent.robot.angle_utils import rad_to_servo_units, speed_to_duration_ms

def resolve_primitive_as_commands(
    name: str,
    angle: float | None = None,
    direction: str | None = None,
    speed: float | None = None,
) -> list[ServoCommand] | None:
    """Resolve a primitive to a list of ServoCommands ready to send to the controller."""
    result = resolve_primitive(name, angle, direction, speed)
    if result is None:
        return None
    joints, final_speed, _ = result
    duration_ms = speed_to_duration_ms(final_speed)
    commands = []
    for joint_name, rad in joints.items():
        servo_id = SERVO_ID_MAP.get(joint_name)
        if servo_id is not None:
            commands.append(ServoCommand(
                servo_id=servo_id,
                position=rad_to_servo_units(rad),
                duration_ms=duration_ms,
            ))
    return commands
```

---

## Step 6 — Update the Server to Use the HAL

In `src/coral_agent/server.py`, replace direct `AiNexSimulator` calls with the `RobotController` interface.

**Current pattern (to remove):**
```python
simulator: AiNexSimulator | None = None
# ...
joints, speed, _ = resolve_primitive(name, ...)
for joint_name, rad in joints.items():
    simulator.set_joint_position(joint_name, rad)
```

**New pattern:**
```python
from coral_agent.robot.interface import RobotController
from coral_agent.robot.sim_controller import SimController
from coral_agent.primitives import resolve_primitive_as_commands

controller: RobotController | None = None

# In lifespan startup:
sim = AiNexSimulator()
controller = SimController(sim)

# In motion execution:
commands = resolve_primitive_as_commands(name, angle, direction, speed)
if commands:
    controller.send_commands(commands)
```

The `AiNexSimulator` instance still exists internally in `SimController` — the viewer thread and MuJoCo loop are unchanged.

---

## Step 7 — Update Joint Limits to Reflect Hardware Resolution

In `src/coral_agent/validation.py`, add a note and verify the limits correspond to what the physical servo can achieve. The physical servo's 0–1000 range maps to 0°–240° (±120° from center). The current `±2.09 rad` (`±119.7°`) limits in `JOINT_LIMITS` are already correct. No change needed here, but document this explicitly.

Also audit tighter ankle limits (`l_ank_pitch`, `r_ank_pitch`: ±1.0 rad; `l_ank_roll`, `r_ank_roll`: ±0.4 rad) — verify these match the physical ankle servo's physical stop positions. In `rad_to_servo_units`, these will clamp to a narrower range than 0–1000, which is expected.

---

## Step 8 — Add a Controller Factory

Create `src/coral_agent/robot/__init__.py`:

```python
from coral_agent.robot.interface import RobotController

def get_controller(mode: str = "sim", **kwargs) -> RobotController:
    if mode == "sim":
        from coral_agent.simulator.mujoco_sim import AiNexSimulator
        from coral_agent.robot.sim_controller import SimController
        sim = AiNexSimulator(**kwargs)
        return SimController(sim)
    elif mode == "hardware":
        # Implemented in Phase 2
        from coral_agent.robot.hardware_controller import AiNexHardwareController
        return AiNexHardwareController(**kwargs)
    else:
        raise ValueError(f"Unknown controller mode: {mode}")
```

This means the entire server startup changes to one line:
```python
controller = get_controller(mode=os.getenv("ROBOT_MODE", "sim"))
```

---

## Step 9 — Verification Checklist

Before moving to Phase 2, verify each item in simulation:

- [ ] All 24 joints are addressable by servo ID via `SERVO_ID_MAP`
- [ ] `rad_to_servo_units` ↔ `servo_units_to_rad` round-trip is lossless within 0.24° resolution
- [ ] `speed_to_duration_ms` produces reasonable durations for all primitive speed values
- [ ] `SimController.send_commands()` moves joints smoothly over the specified duration
- [ ] Multi-joint commands (e.g. `neutral`) move all joints concurrently, not sequentially
- [ ] `read_feedback()` returns data in the correct `ServoFeedback` format
- [ ] `server.py` no longer imports or calls `set_joint_position` directly — all motion goes through `RobotController`
- [ ] Existing gesture library and LLM pipeline still work end-to-end
- [ ] The `wave`, `point_forward` preset poses produce correct visual output in MuJoCo viewer
- [ ] `ROBOT_MODE=sim` env var selects the simulator backend via the factory

---

## File Summary

| File | Action |
|------|--------|
| `src/coral_agent/robot/__init__.py` | **New** — controller factory (`get_controller`) |
| `src/coral_agent/robot/interface.py` | **New** — `ServoCommand`, `ServoFeedback`, `RobotController` ABC |
| `src/coral_agent/robot/servo_config.py` | **New** — `SERVO_ID_MAP`, `JOINT_NAME_MAP` |
| `src/coral_agent/robot/angle_utils.py` | **New** — `rad_to_servo_units`, `servo_units_to_rad`, `speed_to_duration_ms` |
| `src/coral_agent/robot/sim_controller.py` | **New** — `SimController` implementing `RobotController` |
| `src/coral_agent/primitives.py` | **Modify** — add `resolve_primitive_as_commands()` |
| `src/coral_agent/server.py` | **Modify** — replace direct sim calls with `RobotController` interface |
| `src/coral_agent/simulator/mujoco_sim.py` | **No change** — stays as an internal detail of `SimController` |
| `src/coral_agent/validation.py` | **No change** — limits already match hardware; add documentation comment |
