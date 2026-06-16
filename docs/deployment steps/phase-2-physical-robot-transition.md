# Phase 2: Physical Robot Transition

**Prerequisite:** Phase 1 complete. The entire motion pipeline goes through the `RobotController` interface, commands are expressed as `ServoCommand(servo_id, position_units, duration_ms)`, and `ROBOT_MODE=sim` runs the simulator backend.

**Goal:** Swap in a `AiNexHardwareController` backend that sends real Hiwonder serial packets over UART to the physical robot. No changes needed upstream of `RobotController`.

---

## Step 1 — Network Access to the Robot

The AiNex RPi 5 creates a WiFi hotspot on first boot.

1. Power on the robot (switch on the base).
2. Connect your development machine to the robot's WiFi network (SSID and password are printed on the robot or in the "First Start" lesson).
3. SSH into the robot:
   ```bash
   ssh pi@192.168.149.1
   # Default password: raspberry
   ```
4. Confirm Python 3 is available and note the serial port for the servo bus:
   ```bash
   ls /dev/ttyAMA*   # typically /dev/ttyAMA1 or /dev/ttyUSB0
   python3 --version
   ```

Keep this SSH connection open as your main console during testing.

---

## Step 2 — Install Dependencies on the Robot

```bash
# On the robot (over SSH)
pip3 install pyserial loguru
```

Copy the `coral_agent` package to the robot. The simplest method during initial testing:

```bash
# On your dev machine
rsync -av --exclude='.venv' --exclude='__pycache__' \
  src/coral_agent/ pi@192.168.149.1:~/coral_agent/
```

Or run the agent server on your dev machine and have it connect to the robot's serial port over the network (see Step 5 for the remote option).

---

## Step 3 — Confirm Servo IDs

Before running any code, verify the servo ID mapping from `servo_config.py` matches the physical wiring. The AiNex "Robot Hardware Structure" lesson lists the default servo IDs.

Use the Hiwonder servo test tool (pre-installed on the robot) to ping each servo:

```bash
# On the robot
python3 -c "
from hiwonder.servo_controller import ServoController
sc = ServoController('/dev/ttyAMA1', 115200)
for sid in range(1, 25):
    pos = sc.read_position(sid)
    if pos is not None:
        print(f'Servo {sid}: position={pos}')
"
```

Update `SERVO_ID_MAP` in `src/coral_agent/robot/servo_config.py` if any IDs differ from the Phase 1 defaults.

---

## Step 4 — Implement the Hardware Serial Driver

Create `src/coral_agent/robot/hiwonder_serial.py`.

This implements the Hiwonder bus servo protocol: half-duplex UART, binary packets with CRC8 checksum.

```python
import serial
import threading
import time

HEADER = bytes([0x55, 0x55])

CMD_MOVE_TIME_WRITE = 1    # Move servo to position in given time
CMD_POS_READ        = 28   # Read current servo position

def _checksum(data: bytes) -> int:
    return (~sum(data)) & 0xFF

def build_move_packet(servo_id: int, position: int, duration_ms: int) -> bytes:
    """Build a SERVO_MOVE_TIME_WRITE packet."""
    pos_lo  = position & 0xFF
    pos_hi  = (position >> 8) & 0xFF
    time_lo = duration_ms & 0xFF
    time_hi = (duration_ms >> 8) & 0xFF
    params = bytes([servo_id, 7, CMD_MOVE_TIME_WRITE, pos_lo, pos_hi, time_lo, time_hi])
    return HEADER + params + bytes([_checksum(params)])

def build_pos_read_packet(servo_id: int) -> bytes:
    """Build a position read request packet."""
    params = bytes([servo_id, 3, CMD_POS_READ])
    return HEADER + params + bytes([_checksum(params)])

class HiwonderSerial:
    def __init__(self, port: str = '/dev/ttyAMA1', baudrate: int = 115200):
        self._serial = serial.Serial(port, baudrate, timeout=0.05)
        self._lock = threading.Lock()

    def send_move(self, servo_id: int, position: int, duration_ms: int) -> None:
        packet = build_move_packet(servo_id, position, duration_ms)
        with self._lock:
            self._serial.write(packet)

    def read_position(self, servo_id: int) -> int | None:
        """Request and read back a servo's current position (0–1000)."""
        packet = build_pos_read_packet(servo_id)
        with self._lock:
            self._serial.reset_input_buffer()
            self._serial.write(packet)
            time.sleep(0.002)  # give servo time to respond
            response = self._serial.read(8)
        if len(response) < 8 or response[:2] != HEADER:
            return None
        pos_lo = response[5]
        pos_hi = response[6]
        return pos_lo | (pos_hi << 8)

    def close(self) -> None:
        self._serial.close()
```

---

## Step 5 — Implement the Hardware Controller

Create `src/coral_agent/robot/hardware_controller.py`.

This implements `RobotController` using `HiwonderSerial`. It is a direct swap for `SimController`.

```python
from coral_agent.robot.interface import RobotController, ServoCommand, ServoFeedback
from coral_agent.robot.servo_config import SERVO_ID_MAP, JOINT_NAME_MAP
from coral_agent.robot.hiwonder_serial import HiwonderSerial

# Stand pose in Hiwonder units (500 = center/neutral for most joints)
# Verify these values match the physical robot's stable standing pose
# before running. They should mirror the 'stand' keyframe in ainex.xml.
STAND_POSE: dict[int, int] = {servo_id: 500 for servo_id in JOINT_NAME_MAP}

class AiNexHardwareController(RobotController):
    def __init__(self, port: str = '/dev/ttyAMA1'):
        self._serial = HiwonderSerial(port=port)

    def send_commands(self, commands: list[ServoCommand]) -> None:
        """Send all commands to the servo bus. The bus handles concurrent motion."""
        for cmd in commands:
            self._serial.send_move(cmd.servo_id, cmd.position, cmd.duration_ms)

    def read_feedback(self, servo_ids: list[int]) -> list[ServoFeedback]:
        """Read position from each servo. Temperature/voltage require additional
        command codes not yet implemented — return safe placeholder values."""
        feedback = []
        for servo_id in servo_ids:
            pos = self._serial.read_position(servo_id)
            if pos is not None:
                feedback.append(ServoFeedback(
                    servo_id=servo_id,
                    position=pos,
                    temperature=0,   # TODO: implement CMD_TEMP_READ (Cmd=26)
                    voltage=0,       # TODO: implement CMD_VIN_READ (Cmd=27)
                ))
        return feedback

    def reset_to_stand(self) -> None:
        commands = [
            ServoCommand(servo_id=sid, position=pos, duration_ms=2000)
            for sid, pos in STAND_POSE.items()
        ]
        self.send_commands(commands)

    def get_joint_positions(self) -> dict[str, int]:
        positions = {}
        for joint_name, servo_id in SERVO_ID_MAP.items():
            pos = self._serial.read_position(servo_id)
            if pos is not None:
                positions[joint_name] = pos
        return positions

    def close(self) -> None:
        self._serial.close()
```

---

## Step 6 — Enable Hardware Mode

No changes needed in `server.py`. Set the environment variable on the robot:

```bash
export ROBOT_MODE=hardware
export SERIAL_PORT=/dev/ttyAMA1   # or whichever port the servo bus is on
python3 -m coral_agent.server
```

The factory in `src/coral_agent/robot/__init__.py` (from Phase 1) already handles this:

```python
elif mode == "hardware":
    from coral_agent.robot.hardware_controller import AiNexHardwareController
    port = kwargs.get("port", os.getenv("SERIAL_PORT", "/dev/ttyAMA1"))
    return AiNexHardwareController(port=port)
```

---

## Step 7 — Calibration: Verify Stand Pose Units

The `STAND_POSE` dict in `hardware_controller.py` initializes every servo to `500` (center). The physical robot's natural standing pose likely requires some joints to be offset from center. Before running any motion commands:

1. Power on the robot and let it reach its default position.
2. Call `get_joint_positions()` and record the values:
   ```bash
   python3 -c "
   from coral_agent.robot import get_controller
   ctrl = get_controller(mode='hardware')
   print(ctrl.get_joint_positions())
   "
   ```
3. Use these readings to populate `STAND_POSE` in `hardware_controller.py` accurately.
4. Verify `reset_to_stand()` safely returns the robot to a stable upright pose before running LLM-driven commands.

---

## Step 8 — Testing Sequence

Test in this order to catch problems early without damaging the robot:

1. **Single servo — head pan only:**
   ```python
   from coral_agent.robot import get_controller
   from coral_agent.robot.interface import ServoCommand
   ctrl = get_controller(mode='hardware')
   ctrl.send_commands([ServoCommand(servo_id=1, position=600, duration_ms=1000)])
   # Should turn head right slowly. Servo 1 = head_pan
   ctrl.send_commands([ServoCommand(servo_id=1, position=500, duration_ms=1000)])
   # Returns to center
   ```

2. **Head only (both axes):** Test `head_turn` and `head_tilt` primitives through the full pipeline.

3. **One arm (right arm only):** Test `right_arm_forward` and `right_elbow_bend` primitives. Keep the other arm physically supported.

4. **Neutral / reset:** Test `reset_to_stand()` returns to safe pose.

5. **Voice pipeline end-to-end:** Start the full server, connect the frontend, and issue a simple voice command ("look left").

---

## Step 9 — Safety Monitoring (Recommended Before Extended Use)

Once basic commands work, add temperature monitoring. The physical servo responds to `CMD_TEMP_READ` (Cmd=26) with a single byte (Celsius). Add to `HiwonderSerial`:

```python
CMD_TEMP_READ = 26

def read_temperature(self, servo_id: int) -> int | None:
    params = bytes([servo_id, 3, CMD_TEMP_READ])
    packet = HEADER + params + bytes([_checksum(params)])
    with self._lock:
        self._serial.reset_input_buffer()
        self._serial.write(packet)
        time.sleep(0.002)
        response = self._serial.read(7)
    if len(response) < 7 or response[:2] != HEADER:
        return None
    return response[5]
```

Add a background monitoring thread to `AiNexHardwareController` that polls all servos every 5 seconds and logs a warning if any servo exceeds 50°C. Halt new commands if any servo reaches 60°C.

---

## Rollback

If a command sends a joint to a bad position:
1. The robot has a physical power switch — cut power immediately.
2. SSH back in and call `reset_to_stand()` before re-enabling motion.
3. If a servo is unresponsive after a bad packet, power-cycle the robot (the Hiwonder bus clears on power-cycle).

---

## File Summary

| File | Action |
|------|--------|
| `src/coral_agent/robot/hiwonder_serial.py` | **New** — UART driver, packet builder, position reader |
| `src/coral_agent/robot/hardware_controller.py` | **New** — `AiNexHardwareController` implementing `RobotController` |
| `src/coral_agent/robot/__init__.py` | **Modify** — enable `mode="hardware"` branch in factory |
| Everything else | **No change** — Phase 1 abstraction absorbs the entire difference |

Total new code for Phase 2: ~100 lines. The abstraction built in Phase 1 is doing all the heavy lifting.
