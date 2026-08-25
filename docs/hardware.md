# Hardware & Pi Operations

Working notes for the physical AiNex robot: how to reach it, how to get code onto it, and what to check when something misbehaves.

For first-time setup and the normal run procedure, see the [README](../README.md) — this document covers everything around it rather than repeating it.

The manufacturer's documentation for the AiNex lives in [this Google Drive folder](https://drive.google.com/drive/folders/1kyhah0bdW4d8omzYjot0Kq2f50l5GYcB).

---

## 1. The mental model

Three machines, not two:

| Layer | What it is | Where you land |
|---|---|---|
| **Mac** | Frontend, LLM server, vision, TTS | your laptop |
| **Pi** | Raspberry Pi running Raspberry Pi OS | `ssh pi@raspberrypi.local`, home is `/home/pi` |
| **`ainex` container** | Docker container on the Pi with ROS Noetic | `docker exec -it ainex bash`, then `su - ubuntu` |

Facts that follow from this and cause most of the confusion:

- **All ROS code lives inside the container**, at `/home/ubuntu/ros_ws/src/`. Nothing on the Pi's own filesystem is on the ROS path.
- **You cannot `scp` directly into the container.** Every file transfer is two hops: Mac → Pi, then Pi → container.
- **The container should always be running.** Most of the time you don't need to start it before copying files into it.

---

## 2. Getting in

### The helper scripts

Two zsh helpers live in [utils/](../utils/). Both wrap the same two-hop Mac → Pi → container path so you don't have to type it out.

| Script | What it does |
|---|---|
| [`pi.sh`](../utils/pi.sh) | One command from Mac to a shell inside the container |
| [`dump.sh`](../utils/dump.sh) | Copies a file or directory from your local repo into the container |

**One-time setup.** Both expect to be on your `PATH` under a short name:

```bash
sudo mv utils/pi.sh   /usr/local/bin/pi   && sudo chmod +x /usr/local/bin/pi
sudo mv utils/dump.sh /usr/local/bin/dump && sudo chmod +x /usr/local/bin/dump
```

Both also require `sshpass`, which they use to pass the Pi's password non-interactively:

```bash
brew install sshpass
```

If Homebrew refuses to install `sshpass` from core, you'll need a third-party tap — or set up SSH keys to the Pi and strip the `sshpass` wrapper out of both scripts, which is the better long-term fix.

**Before first use, edit the CONFIG block at the top of each script.** They carry hard-coded values that will not be right for you:

- `REPO_ROOT` in `dump.sh` points at `/Users/scottfukuda/ainex_skeleton_following` — a local path on one machine, and a *different* repo from this one. `dump` refuses any file outside it, so this must be changed before the script will do anything.
- `PI_USER`, `PI_HOST`, and `PI_PASSWORD` are hard-coded in both.

### Network

The robot is on the **coroblab** wifi. Both the Mac and the Pi must be on it.

- Hostname: `raspberrypi.local`
- IP: `192.168.8.219` (also the default for `ROBOT_IP`)

Use the hostname when you can and the IP when mDNS is being unreliable.

The physical router is a GL.iNet GL-BE3600(Slate 7) portable router.

### Credentials

| | |
|---|---|
| Username | `pi` |
| Password | `raspberrypi` |

These are the Pi's login, used for SSH, for RealVNC, and by both helper scripts (`PI_USER` / `PI_PASSWORD` in their CONFIG blocks). The `ubuntu` user inside the container is reached with `su - ubuntu` and needs no password.

### SSH

```bash
ssh pi@raspberrypi.local
docker exec -it ainex bash
su - ubuntu
cd /home/ubuntu
```

With [`pi.sh`](../utils/pi.sh) installed, one command replaces all four:

```bash
pi
```

It SSHes in, runs `docker exec -it ainex bash`, switches to the `ubuntu` user, lands in `/home/ubuntu`, and leaves you at an interactive shell. Exiting drops you all the way back to the Mac rather than to the Pi.

Use plain `ssh pi@raspberrypi.local` when you actually want a shell on the **Pi itself** rather than inside the container — for example to run `docker` commands or check the host's networking.

### GUI access over RealVNC

The pi contains an application that you can use to manually control the robot (AiNex Controller). That is, you can set the servo motors to specific values and execute predefined motions.

**On the Mac, each session:**

1. Install **RealVNC Viewer**.
2. Connect to `raspberrypi.local` (or `192.168.8.219` if the hostname doesn't resolve).

Notes:

- VNC serves the Pi's desktop, **not** the container. Anything inside `ainex` is still reached through `docker exec`.
- The session is only as good as the wifi. See the latency notes in §5 if the desktop is unusably slow.

---

## 3. Getting files onto the robot

### `dump` (preferred)

[`dump.sh`](../utils/dump.sh) does both hops in one command. Run it from inside the repo named by `REPO_ROOT` in its CONFIG block:

```bash
dump <file_or_dir>
```

It then prompts:

```
Write to: /home/ubuntu/ros_ws/src/____
```

Enter a path relative to `/home/ubuntu/ros_ws/src/` — for example `demos`. Leading and trailing slashes are stripped, and an empty answer aborts.

The file lands in three places:

```
local:      <REPO_ROOT>/<relative path>
Pi staging: /home/pi/scp/<relative path>
container:  ainex:/home/ubuntu/ros_ws/src/<entered>/<basename>
```

Note the asymmetry: the **Pi staging copy mirrors your local directory structure**, while the **container copy is flattened** — only the basename is appended to the destination you typed. `dump demos/test.py` answered with `demos` lands at `.../src/demos/test.py`, not `.../src/demos/demos/test.py`.

Example:

```bash
dump demos/test_head_servo.py     # then type: demos
```

Directories work too and are copied recursively.

**What it will and won't do:**

- It refuses any file outside `REPO_ROOT`, printing the expected and actual paths.
- It **creates the staging directory on the Pi** but **not** the destination directory inside the container. If `docker cp` fails, the usual cause is that `/home/ubuntu/ros_ws/src/<what you typed>/` doesn't exist yet — the script says as much in its error. Create it inside the container first, then re-run.
- It does **not** set the executable bit. New ROS nodes still need `chmod +x` inside the container (see §5).
- Each run prints the three resolved paths before transferring, so check that line if a file ends up somewhere unexpected.

### Manual, two steps

When `dump` isn't available or you need a non-standard destination.

**Step 1 — Mac to Pi:**

```bash
scp /path/to/file.py pi@raspberrypi.local:/home/pi/file.py
scp -r /path/to/folder pi@raspberrypi.local:/home/pi/folder     # whole folder
```

**Step 2 — Pi to container:**

```bash
ssh pi@raspberrypi.local
docker cp /home/pi/file.py ainex:/home/ubuntu/ros_ws/src/<package>/file.py
docker cp /home/pi/folder/. ainex:/home/ubuntu/ros_ws/src/<package>/    # whole folder
```

### Manual, one line

Both hops chained from the Mac, no interactive SSH:

```bash
scp /path/to/file.py pi@raspberrypi.local:/home/pi/file.py \
  && ssh pi@raspberrypi.local \
     'docker cp /home/pi/file.py ainex:/home/ubuntu/ros_ws/src/<package>/file.py'
```

### When a rebuild is needed

Files under `nodes/` take effect immediately. Changes to `CMakeLists.txt`, `package.xml`, or `srv/` require a rebuild inside the container:

```bash
cd ~/ros_ws && catkin build ainex_demo && source devel/setup.bash
```

---

## 4. Running code in the container

`pyrun` is presumed to be a convenience alias/function set up locally in the `ubuntu` user's shell inside the container — it is **not** defined anywhere in this repo (no `pyrun` script under `utils/` or elsewhere). If it isn't set up on your Pi, run the script directly instead, e.g. `python3 ~/ros_ws/src/demos/test.py` (source `~/ros_ws/devel/setup.bash` first if the script imports ROS packages), or use `rosrun ainex_demo <node>.py` for an actual ROS node under `ainex_demo/nodes/`.

```bash
pyrun <path from ros_ws/src>
```

For example:

```bash
pyrun demos/test.py
```

For the full demo launch, source the workspace and start the launch file:

```bash
cd ~/ros_ws && source devel/setup.bash
roslaunch ainex_demo ainex_demo.launch
```

This brings up `robot_server` along with the rest of the demo nodes. Confirm it is
up from the Mac:

```bash
curl http://192.168.8.219:9000/health
```

See also the README's Pi run section.

---

## 5. Troubleshooting

### The script won't start

**`ERROR: cannot launch node of type [ainex_demo/server.py]: Cannot locate node of type [server.py] in package [ainex_demo].`**

The file isn't executable. ROS requires the executable bit on node scripts:

```bash
chmod +x ~/ros_ws/src/ainex_demo/nodes/*.py
```

This bites most often right after copying a new node in, since the transfer doesn't always preserve permissions.

**Pipeline won't start at all** — restart the GUI and try again.

### Port already in use

Change the port. The relevant variables are `ROBOT_AGENT_PORT` (Mac side, the port it dials) and `AGENT_PORT` (Pi side, the port the server binds to); they must agree. See the README's environment variable table.

### Very high latency

In order of likelihood:

1. **Poor connection to the coroblab wifi** — this is the usual cause.
2. **The Mac is in Low Power Mode.** Turn it off; it throttles enough to show up as pipeline lag.

### Camera

- **Blurry image** — the lens is manually focusable. Adjust it by hand.
- **No image at all when live streaming** — unplug the camera, plug it back in, then try a different USB port.

### A joint moves less on the robot than in the sim

**Servo 20 — the right elbow bend — is mechanically damaged.** It cannot travel its
full range, so it is capped in software: `HW_SERVO_LIMITS` in
`src/robot/hardware_angle_utils.py` gives `r_el_yaw` a range of `(450, 850)` where
an undamaged servo would get the full `0–1000`. Note that the physical elbow *bend*
is `*_el_yaw` (servos 19/20), not `*_el_pitch` — the YAML joint names are
misleading, and `*_el_pitch` (17/18) is forearm rotation.

The symptom is one-sided: **the pose looks correct in the simulator and correct
after adjustments, and only the physical robot comes up short.** That is expected
given how the two targets are clamped:

- `rad_to_hardware_units` clamps every target to `HW_SERVO_LIMITS` **silently** —
  no warning is logged when a command is cut back, so nothing in the logs
  distinguishes "reached" from "clamped".
- The simulator has no equivalent cap. Every joint in `assets/ainex/ainex.xml`
  inherits the same default `range="-2.09 2.09"` (±120°), so MuJoCo happily shows
  motion the servos will never reproduce.

Two things make the elbows the most visible case. Their stand pose sits *exactly on*
a range bound (`l_el_yaw` stands at pulse 150, the floor; `r_el_yaw` at 850, the
ceiling), so from stand the hardware elbow has travel in one direction only and tops
out around 90° of bend. And the left/right forearm ranges are not mirrored —
`l_el_pitch` gets `(440, 653)` but `r_el_pitch` only `(320, 560)` — so a pose that is
symmetric in the sim can land a few degrees apart on the two arms.

Before chasing this as a software bug, move the joint by hand and confirm the servo
itself reaches the angle. If a range in `HW_SERVO_LIMITS` turns out to be wrong,
edit it there and nowhere else: `src/validation.py` derives the sim-radian
`JOINT_LIMITS` from that table, so the two stay in lockstep. Every range must still
contain its joint's `STAND_PULSE`, or the stand pose becomes unreachable.

One inconsistency to be aware of: the comments on `r_el_yaw` say "never command
below 360" while the range floor is actually set to 450. The code is the stricter of
the two, so it is safe, but the true mechanical floor has not been re-measured.

---

## 6. Conventions and gotchas

**Left and right are the robot's.** Throughout the code, "left" and "right" refer to the robot's own left and right, not the perspective of a person facing it. The retargeting mirrors accordingly: a person's right arm drives the robot's left arm.

**Keep the battery above 10V.** A full charge takes roughly one hour. To maintain the robot's optimal performance, charge it promptly once the voltage drops to **≤10V**

**The Pi hostname and IP are hard-coded as defaults** in `src/robot/hardware_controller.py` and the README. If the robot's address changes, override `ROBOT_IP` rather than editing the default.
