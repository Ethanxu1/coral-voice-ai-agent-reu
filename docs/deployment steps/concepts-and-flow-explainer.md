# Concepts & Flow Explainer

This document explains the ideas behind the two deployment plans in plain language. It is meant to be read before (or alongside) the technical plans. No prior robotics experience assumed.

---

## Part 1 — What Is Actually Happening Right Now

Before explaining what changes, it helps to understand the current setup clearly.

### The Current Flow (Simulation)

When you speak a command like *"raise your right arm"*, here is what happens step by step:

```
Your voice
  → Whisper (speech-to-text) converts it to text
  → GPT-4o-mini reads the text and decides which motion to use
  → The motion primitive system translates that into joint angle numbers
  → MuJoCo receives those numbers and moves the robot on screen
```

Each of those arrows is a hand-off between different pieces of software. The robot you see moving on screen is a visual simulation — nothing physically moves.

### What Is MuJoCo?

**MuJoCo** (Multi-Joint dynamics with Contact) is a physics simulator. Think of it like a very accurate video game physics engine. It knows the robot's body shape, weight, joint positions, and physical limits. When you tell it to move a joint, it calculates how the robot would actually move including gravity and balance, then draws it on screen.

The robot model lives in a file called `assets/ainex/ainex.xml`. That file describes every bone, joint, and motor of the AiNex robot in a format MuJoCo understands.

### What Is a Joint?

A **joint** is any point on the robot where one part can rotate relative to another — like your elbow, shoulder, or neck. The AiNex robot has 24 joints total:

- 2 in the head (pan left/right, tilt up/down)
- 5 in each arm × 2 = 10 (shoulder, elbow, wrist, gripper)
- 6 in each leg × 2 = 12 (hip, knee, ankle)

In the simulator, each joint is controlled by an **actuator** — the software equivalent of a motor. You tell the actuator "go to angle X" and MuJoCo figures out the physics.

### What Is a Servo?

On the **physical** robot, joints are moved by devices called **servos** (short for servo motors). A servo is a small motor with a built-in position sensor. You send it a command saying "go to position 650" and it drives itself to that angle and holds there.

The AiNex uses **Hiwonder bus servos**. "Bus" means all 24 servos share a single wire — commands travel down the wire and each servo listens for its own ID number, like an address.

### Radians vs. Servo Units — Why This Matters

This is one of the most important translation problems between simulation and hardware.

**In MuJoCo (simulation):** Joint angles are measured in **radians** — a mathematical unit of angle. 0 radians = straight ahead (center). Positive/negative numbers mean rotated one way or the other. The full range the AiNex joints support is roughly −2.09 to +2.09 radians (which is ±120 degrees).

**On the physical robot:** The Hiwonder servos don't understand radians. They use an integer from **0 to 1000**, where:
- `0` = fully rotated one way (0 degrees)
- `500` = center position (120 degrees — the servo's physical midpoint)
- `1000` = fully rotated the other way (240 degrees)

So when the simulation says "set head_pan to −0.785 radians" (which is 45 degrees to the left), we need to translate that into something like `313` for the physical servo.

The conversion math isn't complicated — it's just multiplication and offsetting by the center — but it must be done consistently everywhere or joints will go to the wrong positions.

---

## Part 2 — Key Terms Dictionary

### Hardware Abstraction Layer (HAL)

The **Hardware Abstraction Layer** is a software layer that sits between your main program logic and the actual hardware (or simulator). Its job is to hide the details of *how* commands get executed so the rest of your code doesn't need to know.

Think of it like a universal remote control. Whether you're controlling a Sony TV or a Samsung TV, you press the same buttons. The remote figures out which specific infrared signals to send for each brand. Your code is the person pressing buttons; the HAL is the remote; the simulator and physical robot are the two TV brands.

In the plan, the HAL is the `RobotController` class. Your server sends it `ServoCommand` objects. Whether those commands go to MuJoCo or to the physical robot over a wire is handled internally.

### ServoCommand

A **ServoCommand** is a small data package with three pieces of information:
1. **servo_id** — which servo to move (1 through 24)
2. **position** — where to move it (0 to 1000 in Hiwonder units)
3. **duration_ms** — how long the move should take in milliseconds (e.g. 1000 = 1 second)

This matches exactly what the physical robot expects to receive. By making the simulation also accept `ServoCommand` objects, you ensure the same code works for both.

### ServoFeedback

**Feedback** means information the robot sends *back* to your computer telling you its current state. The physical servos can report:
- Their **current position** (where they actually are, not where you told them to go)
- Their **temperature** (servos overheat if worked too hard)
- Their **voltage** (battery level)

In simulation, none of this exists — MuJoCo gives you perfect information instantly. The plan has the simulator return *fake* feedback with safe placeholder values (e.g. temperature = 35°C, voltage = 11.1V) so the rest of the code doesn't need to know the difference.

### Motion Primitive

A **motion primitive** is a named, reusable movement — a building block for robot behavior. Instead of the LLM calculating raw joint angles from scratch every time, it picks from a library of tested movements.

Examples:
- `right_arm_forward(angle=90)` — raise right arm 90 degrees forward
- `head_turn(direction="left", angle=45)` — turn head 45 degrees left
- `neutral()` — return all joints to standing position

Each primitive is a Python function that, given an angle and optional direction, returns a dictionary of `{joint_name: target_angle}`. Phase 1 adds a second version of this that returns a list of `ServoCommand` objects instead of raw radians.

### UART / Serial Communication

**UART** (Universal Asynchronous Receiver-Transmitter) is a way of sending data over a wire, one bit at a time. It's one of the oldest and simplest communication protocols in electronics.

The physical AiNex robot uses UART at **115200 baud** — meaning 115,200 bits per second travel down the wire. All 24 servos are daisy-chained on this wire. When your code sends a packet addressed to servo ID 3, every servo on the bus sees the packet, but only servo 3 acts on it.

**Serial** is the general term for this kind of one-bit-at-a-time communication. You'll see the port listed as `/dev/ttyAMA1` on the Raspberry Pi — that's Linux's name for the serial port the servo bus is connected to.

### Packet

A **packet** is a structured block of bytes sent over a wire. Each packet has a defined format so the receiver knows how to interpret it. The Hiwonder servo packet format is:

```
[0x55] [0x55] [ID] [Length] [Command] [Param1] [Param2...] [Checksum]
```

- `0x55 0x55` — a fixed "header" that signals the start of a new packet (like saying "attention!")
- `ID` — which servo this packet is for
- `Length` — how many bytes follow
- `Command` — what to do (e.g. command #1 = "move to position")
- `Params` — the arguments (e.g. target position, duration)
- `Checksum` — a number calculated from all the previous bytes used to detect transmission errors

### Checksum

A **checksum** is a error-detection value. Before sending a packet, the sender runs a calculation over all the bytes and appends the result. The receiver runs the same calculation on what it received and compares. If they don't match, something got corrupted in transit and the packet is ignored.

The Hiwonder protocol uses a simple checksum: add up all the data bytes, take the bitwise NOT (flip all the bits), and keep only the last 8 bits. It's a quick sanity check, not strong security.

### Half-Duplex

The Hiwonder serial bus is **half-duplex**, meaning the wire can carry data in both directions, but not at the same time. Your code sends a command, then has to stop transmitting and switch to "listen mode" before the servo can send a reply. This is why there's a small `time.sleep(0.002)` (2 milliseconds) after sending a read request — you need to give the bus time to switch directions and the servo time to respond.

### Raspberry Pi 5 (RPi 5)

The **Raspberry Pi 5** is the small computer inside the physical AiNex robot. It runs Ubuntu Linux and handles all the software — receiving commands, sending servo packets, running ROS (the robot's middleware), and hosting the camera feed. When you SSH into the robot, you're connecting to this computer.

### SSH

**SSH** (Secure Shell) is a way to open a command-line terminal on a remote computer over a network. It's how you'll run code and check logs on the robot's internal Raspberry Pi from your development laptop without needing a physical screen or keyboard connected to the robot.

### ROS

**ROS** (Robot Operating System) is a framework for robot software. Despite the name, it's not really an operating system — it's a set of tools and conventions for how different parts of a robot's software talk to each other. The AiNex ships with ROS pre-installed and uses it for some of its built-in features (walking, vision, etc.).

The CORAL project doesn't currently use ROS. This is fine for Phase 1 and Phase 2 — you can send servo commands directly over serial without going through ROS at all.

---

## Part 3 — The Logic Flow, Explained

### Current Flow (Before Phase 1)

```
User speaks
    ↓
Whisper (converts speech to text)
    ↓
server.py receives the text
    ↓
GPT-4o-mini reads the text + a list of available primitives
GPT decides: "this means right_arm_forward at 90 degrees"
    ↓
primitives.py: right_arm_forward(90) runs
Returns: {"r_sho_pitch": 1.571}   ← that's 90 degrees in radians
    ↓
server.py calls: simulator.set_joint_position("r_sho_pitch", 1.571)
    ↓
MuJoCo moves the arm on screen instantly
```

The problem with this flow: `simulator.set_joint_position("r_sho_pitch", 1.571)` is a call that only MuJoCo understands. There's no equivalent on the physical robot. You can't just replace the robot with the physical one — the entire "language" of commands is different.

### After Phase 1 — Same Flow, Different Language

```
User speaks
    ↓
Whisper (converts speech to text)
    ↓
server.py receives the text
    ↓
GPT-4o-mini decides: "right_arm_forward at 90 degrees"
    ↓
primitives.py: resolve_primitive_as_commands("right_arm_forward", angle=90)
Returns: [ServoCommand(servo_id=3, position=917, duration_ms=1000)]
         ↑ "move servo #3 to position 917, taking 1 second"
    ↓
server.py calls: controller.send_commands([...])
    ↓
SimController receives the command
Converts position 917 back to radians: ~1.571
Calls MuJoCo over 1 second (interpolating smoothly)
MuJoCo moves the arm on screen
```

The critical difference: the command is now expressed in the physical robot's language (`ServoCommand` with servo ID and integer units). The `SimController` translates it back to radians internally for MuJoCo. When you swap to the physical robot, you swap `SimController` for `AiNexHardwareController` — everything above that layer stays the same.

### After Phase 2 — Real Robot

```
User speaks
    ↓
[identical to above until...]
    ↓
server.py calls: controller.send_commands([ServoCommand(servo_id=3, position=917, duration_ms=1000)])
    ↓
AiNexHardwareController receives the command
HiwonderSerial builds a binary packet:
  [0x55][0x55][03][07][01][95][03][E8][03][checksum]
   header  ID  len cmd  pos(917)   time(1000ms)
    ↓
The packet travels down the UART wire to the servo bus
Servo #3 (r_sho_pitch) receives it, confirms its ID matches
Servo drives itself to position 917 over 1000ms
    ↓
Arm raises physically
```

### Why the Phases Are Ordered This Way

Phase 1 is harder than Phase 2, but it's done first because it makes Phase 2 trivial. It's like spending a week building an adapter that lets you plug any device into any socket — after that, plugging in a new device takes 10 seconds.

If you tried to go straight to Phase 2 without Phase 1, you'd have to rewrite `server.py`, the primitives, and the validation code all at once while also dealing with a physical robot that can fall over. By doing Phase 1 first entirely in simulation, you can verify everything is wired up correctly before touching the hardware.

---

## Part 4 — What Could Go Wrong and Why

### Servo ID Mismatch

If `SERVO_ID_MAP` says "head_pan is servo 1" but the physical robot has the head pan wired to servo 3, the robot will move the wrong joint when you say "look left." This is caught by the Step 3 verification in Phase 2 (pinging each servo individually).

### Angle Offset Errors

The physical servo's "center" (position 500) might not align with the robot's natural standing position. Some joints are physically assembled slightly offset. This is why Phase 2 Step 7 reads the actual joint positions *before* running any commands and uses those readings to calibrate the stand pose.

### Temperature and Heat

Servos generate heat when working. If the robot holds a position against gravity for too long, or if you run continuous fast motions, servos can overheat. The Hiwonder servos will cut out at around 70°C to protect themselves. Phase 2 Step 9 describes monitoring for this — it's optional but recommended before any extended demo.

### Timing on the Serial Bus

All 24 servos share one wire. If your code sends 24 commands too fast, packets can collide. The Hiwonder protocol handles this by giving each servo its own ID and having the controller wait slightly between commands. In practice, sending them in a tight loop works fine because the UART hardware buffers the bytes — just don't try to read and write simultaneously (that's what the `_lock` in `HiwonderSerial` prevents).

### The Physical Robot Can Fall

The simulator never falls over. The physical robot can — especially when:
- Commanded to a pose it can't balance in
- Leg servos move while the robot is standing
- Power cuts mid-motion

For Phase 2, start testing with the robot **held off the ground** (suspended from above or seated on a table) and only test arm/head commands first. Add leg commands only after you've verified the pipeline is stable and you understand the robot's balance characteristics.

---

## Summary Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        CORAL Agent Server                        │
│                                                                   │
│  Voice → Whisper → GPT-4o-mini → resolve_primitive_as_commands  │
│                                          │                        │
│                              [ServoCommand list]                  │
│                                          │                        │
│                              controller.send_commands()           │
│                                          │                        │
└──────────────────────────────────────────┼──────────────────────┘
                                           │
              ┌────────────────────────────┤
              │                            │
    ┌─────────▼──────────┐    ┌────────────▼──────────────┐
    │   SimController    │    │  AiNexHardwareController   │
    │  (Phase 1 — sim)   │    │    (Phase 2 — real robot)  │
    │                    │    │                            │
    │ Converts units     │    │ Builds binary UART packet  │
    │ back to radians    │    │ Sends over serial wire     │
    │ Interpolates over  │    │ to servo bus               │
    │ duration in MuJoCo │    │                            │
    └─────────┬──────────┘    └────────────┬──────────────┘
              │                            │
    ┌─────────▼──────────┐    ┌────────────▼──────────────┐
    │   MuJoCo Physics   │    │   24 Hiwonder Servos       │
    │   (on your laptop) │    │   (inside physical robot)  │
    └────────────────────┘    └────────────────────────────┘
```

Everything above the dashed line is identical in both cases. That's the whole point of Phase 1.
