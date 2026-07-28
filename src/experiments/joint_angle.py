"""Joint-angle accuracy experiment: trial plan, angle extraction, session store.

Backs the /experiment/* endpoints in server.py, which the frontend's Joint Angle
Experiment mode (/experiment) drives. Everything here is protocol logic and file
I/O — the capture/dispatch itself lives in server.py so it can reuse the demo's
own /map-features -> /move path (collision clamp + fall check included) rather
than a parallel one that would characterize a pipeline no child experiences.

Protocol: 3 arm poses x 3 reps = 9 trials in randomized order. Per trial, three
angles are recorded per arm at four points — the retargeting output, the
post-safety applied pose, the operator's protractor reading, and (as a process
diagnostic) the CV estimator's view of the human.

The reference for the reported error is the *nominal* human angle — the value
the demonstrator was instructed to hold — not the CV reading. The poses are
chosen to be easy to strike unambiguously, so their nominal angles are trusted
ground truth. Error is therefore end-to-end: |robot achieved - nominal| bundles
CV, retargeting, and servo/mechanical error into one accuracy number. The CV
estimate (est) is retained per trial only to show what MediaPipe saw.
"""

from __future__ import annotations

import csv
import json
import math
import random
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from validation import JOINT_LIMITS
from vision import geometry
from vision.pose_to_robot import _STAND_L_SHO_ROLL, _STAND_R_SHO_ROLL

# ── Experiment design ────────────────────────────────────────────────────────
# Each pose is fully specified by all three nominal angles, chosen so a person
# can strike it unambiguously. nominal_* is the instructed value and the ground
# truth the reported error is scored against (see module docstring).
#
# Conventions (a torso-frame elevation/azimuth decomposition of the upper arm,
# derived from geometry.shoulder_pitch_roll so protractor readings, robot-inverted
# angles, and nominals all share one frame — see _elevation_depth):
#   arm_torso_side -> elevation from straight-down: 0 = arms down, 90 = upper arm
#                     horizontal (out to the side OR forward), 180 = overhead.
#   arm_depth      -> forward deviation from the coronal plane, like a yaw:
#                     0 = arm in the side (coronal) plane, +90 = pointing straight
#                     forward (toward the camera). This is MediaPipe's least
#                     reliable axis; every pose holds it at 0, so the robot's
#                     depth deviation from 0 is itself the error of interest.
#   elbow_bend     -> flexion: 0 = straight, 90 = right angle, 180 = folded.


@dataclass(frozen=True)
class PoseSpec:
    key: str
    label: str
    cue: str
    nominal_depth: float        # forward yaw: 0 = coronal plane, 90 = straight forward
    nominal_torso_side: float   # elevation: 0 = down, 90 = horizontal, 180 = overhead
    nominal_elbow: float        # flexion: 0 = straight, 90 = right angle


POSES: tuple[PoseSpec, ...] = (
    PoseSpec("arms_down", "Arms down at side", "Both arms hanging straight down at your sides, elbows straight", 0.0, 0.0, 0.0),
    PoseSpec("arms_overhead", "Arms straight overhead", "Both arms straight up overhead, elbows straight", 0.0, 180.0, 0.0),
    PoseSpec("muscles", "Muscles pose", "Upper arms straight out to the sides, elbows bent 90 deg (biceps flex)", 0.0, 90.0, 90.0),
)

REPS = 3

MEASUREMENTS: tuple[tuple[str, str], ...] = (
    ("arm_depth", "Arm depth (yaw, +forward)"),
    ("arm_torso_side", "Arm-torso elevation (down/horizontal/overhead)"),
    ("elbow_bend", "Elbow bend"),
)

# Robot arm -> the person's arm it mirrors. pose_to_robot maps the person's
# RIGHT side to the robot's LEFT arm, so a protractor reading on the robot's
# left arm must be compared against the person's right-arm estimate.
ARMS: tuple[tuple[str, str], ...] = (
    ("robot_left", "right"),
    ("robot_right", "left"),
)

# Which robot joint carries each (arm, measurement), for flagging a commanded
# angle sitting on its JOINT_LIMITS bound (a large |robot - nominal| that is a
# mechanical limit, not a retargeting error — e.g. overhead pins l_sho_pitch).
# Approximate: elevation and depth each depend on BOTH shoulder joints, so these
# map each to the shoulder joint that dominates it — pitch for elevation, roll
# for depth deviation.
JOINT_FOR: dict[tuple[str, str], str] = {
    ("robot_left", "arm_torso_side"): "l_sho_pitch",
    ("robot_left", "arm_depth"): "l_sho_roll",
    ("robot_left", "elbow_bend"): "l_el_yaw",
    ("robot_right", "arm_torso_side"): "r_sho_pitch",
    ("robot_right", "arm_depth"): "r_sho_roll",
    ("robot_right", "elbow_bend"): "r_el_yaw",
}

CSV_FIELDS = [
    "session_id", "timestamp", "order_index", "pose", "rep",
    "arm", "human_side", "measurement", "nominal_deg",
    "est_human_deg", "mapped_deg", "applied_deg", "robot_deg",
    "mapped_missing", "joint_limit_clamped",
    "collision_clamped", "safe_fraction", "fall_blocked",
    "photo", "notes",
]


# ── Angle extraction ─────────────────────────────────────────────────────────


def _deg(rad: float) -> float:
    return math.degrees(rad)


def _clamp_unit(x: float) -> float:
    return max(-1.0, min(1.0, x))


def _elevation_depth(pitch_rad: float, roll_rad: float) -> tuple[float, float]:
    """Convert the shoulder pitch/roll decomposition to (elevation, depth), deg.

    Reconstruct the torso-frame unit upper-arm direction from pitch/roll (the
    same decomposition geometry.shoulder_pitch_roll produces), then read:
      elevation = angle from straight-down       (0 down, 90 horizontal, 180 up)
      depth     = forward angle out of the coronal plane (0 in-plane, +90 forward)
    Using the shared pitch/roll intermediate keeps the human (CV) and robot
    (joint-inverted) columns in the exact same frame. `roll_rad` is the outward
    abduction magnitude, so its sign is irrelevant here (only cos(roll) is used).
    """
    sag = math.cos(roll_rad)                 # magnitude of the arm in the sagittal (y-z) plane
    vy = -sag * math.cos(pitch_rad)          # torso up-component (down is -y)
    vz = sag * math.sin(pitch_rad)           # torso forward-component (depth)
    elevation = math.acos(_clamp_unit(-vy))
    depth = math.asin(_clamp_unit(vz))
    return _deg(elevation), _deg(depth)


def estimated_human_angles(body: list[dict]) -> Optional[dict[str, dict[str, float]]]:
    """Per-robot-arm CV angles (degrees) as the estimator perceived them.

    Diagnostic only: the reported error is scored against the nominal, not this.
    Uses the same shoulder decomposition map_features drives the robot from,
    re-expressed as elevation/depth (see _elevation_depth), so the est column
    shows what MediaPipe saw for the pose the demonstrator struck.

    Returns None when the torso frame can't be built — without hips there is no
    reference frame and every arm angle is meaningless, so the trial must be
    recaptured rather than recorded with partial data.
    """
    needed = (
        geometry.LEFT_SHOULDER, geometry.RIGHT_SHOULDER,
        geometry.LEFT_HIP, geometry.RIGHT_HIP,
    )
    if len(body) <= max(needed) or not all("xw" in body[i] for i in needed):
        return None

    R_torso = geometry.torso_frame(
        geometry.world_xyz(body[geometry.LEFT_SHOULDER]),
        geometry.world_xyz(body[geometry.RIGHT_SHOULDER]),
        geometry.world_xyz(body[geometry.LEFT_HIP]),
        geometry.world_xyz(body[geometry.RIGHT_HIP]),
    )

    side_landmarks = {
        "right": (geometry.RIGHT_SHOULDER, geometry.RIGHT_ELBOW, geometry.RIGHT_WRIST),
        "left": (geometry.LEFT_SHOULDER, geometry.LEFT_ELBOW, geometry.LEFT_WRIST),
    }

    out: dict[str, dict[str, float]] = {}
    for arm, human_side in ARMS:
        sh_i, el_i, wr_i = side_landmarks[human_side]
        vals: dict[str, float] = {}
        if len(body) > wr_i and all("xw" in body[i] for i in (sh_i, el_i, wr_i)):
            sh = geometry.world_xyz(body[sh_i])
            el = geometry.world_xyz(body[el_i])
            wr = geometry.world_xyz(body[wr_i])
            pitch, roll_abd = geometry.shoulder_pitch_roll(sh, el, R_torso, side=human_side)
            elevation, depth = _elevation_depth(pitch, roll_abd)
            vals["arm_torso_side"] = elevation
            vals["arm_depth"] = depth
            vals["elbow_bend"] = _deg(geometry.elbow_bend(sh, el, wr))
        out[arm] = vals
    return out


def anatomical_angles(targets: dict[str, float]) -> dict[str, dict[str, float]]:
    """Invert robot joint angles (radians) back to the same anatomical quantities.

    Works on either source of joint angles: the targets /map-features produced,
    or the post-safety joint state read back after the move.

    compute_joint_targets bakes the stand-pose roll offset and per-side sign
    conventions into l_sho_roll / r_sho_roll / *_el_yaw; undoing them here is
    what makes these columns comparable to the estimated-human and protractor
    columns instead of being in robot joint space. elevation/depth need BOTH
    shoulder joints, so they are emitted only when both pitch and roll survive.

    Joints absent from `targets` (visibility or depth gate rejected them) are
    left out — that gating is itself a result worth seeing in the data.
    """
    out: dict[str, dict[str, float]] = {"robot_left": {}, "robot_right": {}}

    if "l_sho_pitch" in targets and "l_sho_roll" in targets:
        roll = targets["l_sho_roll"] - _STAND_L_SHO_ROLL
        elevation, depth = _elevation_depth(targets["l_sho_pitch"], roll)
        out["robot_left"]["arm_torso_side"] = elevation
        out["robot_left"]["arm_depth"] = depth
    if "l_el_yaw" in targets:
        out["robot_left"]["elbow_bend"] = _deg(-targets["l_el_yaw"])

    if "r_sho_pitch" in targets and "r_sho_roll" in targets:
        roll = _STAND_R_SHO_ROLL - targets["r_sho_roll"]
        elevation, depth = _elevation_depth(targets["r_sho_pitch"], roll)
        out["robot_right"]["arm_torso_side"] = elevation
        out["robot_right"]["arm_depth"] = depth
    if "r_el_yaw" in targets:
        out["robot_right"]["elbow_bend"] = _deg(targets["r_el_yaw"])

    return out


def clamped_measurements(targets: dict[str, float], tol: float = 1e-4) -> list[list[str]]:
    """[arm, measurement] pairs whose joint was pinned to a JOINT_LIMITS bound.

    Returned as lists (not tuples) so the result is JSON-ready for the frontend.
    """
    out: list[list[str]] = []
    for (arm, key), joint in JOINT_FOR.items():
        rad = targets.get(joint)
        limit = JOINT_LIMITS.get(joint)
        if rad is None or limit is None:
            continue
        if abs(rad - limit.min) < tol or abs(rad - limit.max) < tol:
            out.append([arm, key])
    return out


def nominal_for(pose: PoseSpec, measurement: str) -> float:
    """The instructed angle for one measurement — the pose's own nominal, which
    is the ground truth the reported error is scored against."""
    if measurement == "arm_torso_side":
        return pose.nominal_torso_side
    if measurement == "arm_depth":
        return pose.nominal_depth
    return pose.nominal_elbow


# ── Trials ───────────────────────────────────────────────────────────────────


@dataclass
class Trial:
    order_index: int
    pose: PoseSpec
    rep: int
    photo: str = ""
    timestamp: str = ""
    est: dict[str, dict[str, float]] = field(default_factory=dict)
    mapped: dict[str, dict[str, float]] = field(default_factory=dict)
    applied: dict[str, dict[str, float]] = field(default_factory=dict)
    clamped: list[list[str]] = field(default_factory=list)
    robot: dict[str, dict[str, float]] = field(default_factory=dict)
    safety: dict = field(default_factory=dict)
    notes: str = ""

    @property
    def name(self) -> str:
        return f"{self.order_index:02d}_{self.pose.key}_rep{self.rep}"

    @property
    def captured(self) -> bool:
        return bool(self.est)

    @property
    def recorded(self) -> bool:
        return bool(self.robot)

    def to_dict(self) -> dict:
        return {
            "order_index": self.order_index,
            "pose": self.pose.key,
            "pose_label": self.pose.label,
            "cue": self.pose.cue,
            "rep": self.rep,
            "captured": self.captured,
            "recorded": self.recorded,
            "photo": self.photo,
            "timestamp": self.timestamp,
            "est": self.est,
            "mapped": self.mapped,
            "applied": self.applied,
            "clamped": self.clamped,
            "robot": self.robot,
            "safety": self.safety,
            "notes": self.notes,
            "nominal": {k: nominal_for(self.pose, k) for k, _l in MEASUREMENTS},
        }


def build_trials(seed: int) -> list[Trial]:
    combos = [
        (pose, rep)
        for pose in POSES
        for rep in range(1, REPS + 1)
    ]
    random.Random(seed).shuffle(combos)
    return [Trial(i + 1, pose, rep) for i, (pose, rep) in enumerate(combos)]


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parents[2], text=True,
        ).strip()
    except Exception:
        return "unknown"


# ── Session store ────────────────────────────────────────────────────────────


class Session:
    """One experiment run on disk: metadata.json, trials.csv, photos/, captures/."""

    def __init__(self, directory: Path, meta: dict, trials: list[Trial]):
        self.dir = directory
        self.meta = meta
        self.trials = trials

    # ── lifecycle ──

    @classmethod
    def create(cls, root: Path, seed: int, meta_extra: dict) -> "Session":
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        directory = root / session_id
        (directory / "photos").mkdir(parents=True, exist_ok=True)
        (directory / "captures").mkdir(parents=True, exist_ok=True)
        meta = {
            "session_id": session_id,
            "started": datetime.now().isoformat(timespec="seconds"),
            "git_sha": git_sha(),
            "seed": seed,
            "poses": [p.key for p in POSES],
            "reps": REPS,
            **meta_extra,
        }
        session = cls(directory, meta, build_trials(seed))
        session.save_meta()
        return session

    @classmethod
    def load(cls, root: Path, session_id: str) -> "Session":
        directory = root / session_id
        meta = json.loads((directory / "metadata.json").read_text())
        trials = build_trials(int(meta.get("seed", 0)))
        session = cls(directory, meta, trials)
        # Captures first (full precision, and the only record of a trial that
        # was captured but not yet recorded — every request reloads from disk,
        # so without this a capture would be forgotten before its readings
        # arrive), then the CSV, which additionally carries those readings.
        session.load_captures()
        session.load_csv()
        return session

    def save_meta(self) -> None:
        (self.dir / "metadata.json").write_text(json.dumps(self.meta, indent=2))

    # ── access ──

    @property
    def session_id(self) -> str:
        return str(self.meta["session_id"])

    def trial(self, order_index: int) -> Trial:
        for t in self.trials:
            if t.order_index == order_index:
                return t
        raise KeyError(f"no trial {order_index}")

    def next_unrecorded(self) -> Optional[int]:
        return next((t.order_index for t in self.trials if not t.recorded), None)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "meta": self.meta,
            "trials": [t.to_dict() for t in self.trials],
            "next_unrecorded": self.next_unrecorded(),
            "recorded_count": sum(1 for t in self.trials if t.recorded),
            "total": len(self.trials),
            "measurements": [{"key": k, "label": lab} for k, lab in MEASUREMENTS],
            "arms": [{"arm": a, "human_side": s} for a, s in ARMS],
            "csv_path": str(self.dir / "trials.csv"),
        }

    # ── capture / record ──

    def store_capture(
        self,
        order_index: int,
        *,
        image_bytes: bytes,
        body_landmarks: list[dict],
        targets: dict[str, float],
        joint_states: Optional[dict[str, float]],
        est: dict[str, dict[str, float]],
        safety: dict,
        leg_mode: str,
    ) -> Trial:
        """Attach a capture to a trial and write the photo + raw record.

        Written at capture time rather than at record time so a capture the
        operator later abandons still leaves a reviewable artifact on disk.
        """
        t = self.trial(order_index)
        t.timestamp = datetime.now().isoformat(timespec="seconds")
        t.est = est
        t.mapped = anatomical_angles(targets)
        # applied = what the pose became after the safety layer, read back from
        # the robot state. With no dispatch there is nothing to read, so the
        # mapped values stand in and the two columns are identical.
        t.applied = anatomical_angles(joint_states) if joint_states else {
            arm: dict(vals) for arm, vals in t.mapped.items()
        }
        t.clamped = clamped_measurements(targets)
        t.safety = safety or {}

        photo_name = f"{t.name}.jpg"
        (self.dir / "photos" / photo_name).write_bytes(image_bytes)
        t.photo = f"photos/{photo_name}"
        (self.dir / "captures" / f"{t.name}.json").write_text(json.dumps({
            "trial": t.name, "order_index": t.order_index,
            "timestamp": t.timestamp, "leg_mode": leg_mode,
            "targets": targets, "joint_states": joint_states,
            "safety": t.safety, "body_landmarks": body_landmarks,
        }))
        return t

    def record(self, order_index: int, readings: dict[str, dict[str, float]], notes: str) -> Trial:
        """Store the protractor readings for a trial and rewrite the CSV.

        Full rewrite (rather than append) so the operator can revisit a trial
        and correct a mistyped reading; 54 rows makes the cost irrelevant.
        """
        t = self.trial(order_index)
        if not t.captured:
            raise ValueError("trial has no capture yet")
        validate_readings(readings)
        t.robot = {arm: dict(vals) for arm, vals in readings.items()}
        t.notes = notes
        self.write_csv()
        return t

    # ── persistence ──

    def load_captures(self) -> None:
        """Restore captured trials from captures/*.json.

        Every angle is recomputed from the stored landmarks and joint values
        rather than persisted separately, so there is one source of truth on
        disk and a reload can never disagree with the capture it came from.
        """
        directory = self.dir / "captures"
        if not directory.exists():
            return
        by_index = {t.order_index: t for t in self.trials}
        by_name = {t.name: t for t in self.trials}
        for path in sorted(directory.glob("*.json")):
            try:
                data = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            t = by_index.get(int(data.get("order_index", -1))) or by_name.get(path.stem)
            if t is None:
                continue
            est = estimated_human_angles(data.get("body_landmarks") or [])
            if est is None:
                continue
            targets = data.get("targets") or {}
            joint_states = data.get("joint_states")
            t.timestamp = data.get("timestamp", "")
            t.est = est
            t.mapped = anatomical_angles(targets)
            t.applied = anatomical_angles(joint_states) if joint_states else {
                arm: dict(vals) for arm, vals in t.mapped.items()
            }
            t.clamped = clamped_measurements(targets)
            t.safety = data.get("safety") or {}
            t.photo = f"photos/{t.name}.jpg"

    def write_csv(self) -> None:
        path = self.dir / "trials.csv"
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            w.writeheader()
            for t in self.trials:
                if not t.recorded:
                    continue
                clamped = {tuple(pair) for pair in t.clamped}
                for arm, human_side in ARMS:
                    for key, _label in MEASUREMENTS:
                        mapped = t.mapped.get(arm, {}).get(key)
                        w.writerow({
                            "session_id": self.session_id,
                            "timestamp": t.timestamp,
                            "order_index": t.order_index,
                            "pose": t.pose.key,
                            "rep": t.rep,
                            "arm": arm,
                            "human_side": human_side,
                            "measurement": key,
                            "nominal_deg": nominal_for(t.pose, key),
                            "est_human_deg": _fmt(t.est.get(arm, {}).get(key)),
                            "mapped_deg": _fmt(mapped),
                            "applied_deg": _fmt(t.applied.get(arm, {}).get(key)),
                            "robot_deg": _fmt(t.robot.get(arm, {}).get(key)),
                            "mapped_missing": int(mapped is None),
                            "joint_limit_clamped": int((arm, key) in clamped),
                            "collision_clamped": int(bool(t.safety.get("collision_clamped"))),
                            "safe_fraction": t.safety.get("safe_fraction", ""),
                            "fall_blocked": int(bool(t.safety.get("fall_blocked"))),
                            "photo": t.photo,
                            "notes": t.notes,
                        })

    def load_csv(self) -> None:
        path = self.dir / "trials.csv"
        if not path.exists():
            return
        by_index = {t.order_index: t for t in self.trials}
        with path.open(newline="") as f:
            for row in csv.DictReader(f):
                t = by_index.get(int(row["order_index"]))
                if t is None:
                    continue
                t.notes = row["notes"]
                arm, key = row["arm"], row["measurement"]
                if row["robot_deg"] != "":
                    t.robot.setdefault(arm, {})[key] = float(row["robot_deg"])


def _fmt(v: Optional[float]) -> str:
    return "" if v is None else f"{v:.2f}"


def validate_readings(readings: dict[str, dict[str, float]]) -> None:
    """All six protractor readings must be present and physically plausible."""
    for arm, _side in ARMS:
        for key, label in MEASUREMENTS:
            value = readings.get(arm, {}).get(key)
            if value is None or not isinstance(value, (int, float)) or math.isnan(float(value)):
                raise ValueError(f"missing reading: {label} — {arm}")
            if not -180.0 <= float(value) <= 180.0:
                raise ValueError(f"reading out of range: {label} — {arm} = {value}")


def list_sessions(root: Path) -> list[dict]:
    """Recent sessions, newest first, for the resume picker."""
    if not root.exists():
        return []
    out = []
    for d in sorted((p for p in root.iterdir() if (p / "metadata.json").exists()), reverse=True):
        try:
            meta = json.loads((d / "metadata.json").read_text())
            session = Session.load(root, d.name)
            out.append({
                "session_id": d.name,
                "started": meta.get("started"),
                "demonstrator": meta.get("demonstrator", ""),
                "recorded_count": sum(1 for t in session.trials if t.recorded),
                "total": len(session.trials),
            })
        except Exception:
            continue
    return out
