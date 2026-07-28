#!/usr/bin/env python3
"""
Web server node — stability, classification & live UI.

Each cycle has two phases:
  * tracking (TRACKING_DURATION s) — buffer each incoming skeleton with its
    clean frame and track the most-stable skeleton via a Gaussian-weighted score.
  * results  (RESULTS_DURATION s)  — tracking is frozen; the most-stable clean
    frame is classified and the UI holds the frame, skeleton and detected move.

Responsibilities:
  * Drives the tracking → results phase clock.
  * Serves a live web UI (camera feed + live/stable skeleton + detected move).
  * At the end of each tracking phase, classifies the clean frame belonging to
    the most-stable skeleton using model/pose_classifier.pt and publishes the
    result on /body_commands for the body node to act on.

Subscribes:
  /stable_gest/image_annotated  (Image)  — annotated camera frames
  /stable_gest/landmarks        (String) — per-frame pose landmarks (JSON)
Publishes:
  /body_commands                (String) — JSON {cycle, move, confidence}
"""
import os
import json
import time
import math
import threading

import cv2
import rospy
import numpy as np
from flask import Flask, Response, render_template_string, request
from sensor_msgs.msg import Image
from std_msgs.msg import String, Bool

import torch
import torch.nn as nn
from torchvision import models, transforms
from PIL import Image as PILImage

from config import TRACKING_DURATION, RESULTS_DURATION

WEB_PORT = 8080

# Topic every node listens on; publishing True tells them all to stop.
SHUTDOWN_TOPIC = '/system/shutdown'

# ── Cycle / stability parameters (gaussian skeleton) ──────────────────────────
# TRACKING_DURATION / RESULTS_DURATION are imported from config (shared with the
# body node so it can't pull the classifier in just to read a constant).
STABILITY_N       = 3      # Gaussian neighbour half-window for stability scoring
STABILITY_SIGMA   = 1.0    # Gaussian σ for stability scoring
REQUIRED_LANDMARKS = {11, 12, 13, 14, 15, 16}  # shoulders, elbows, wrists
PRESENCE_THRESH    = 0.4
VISIBILITY_THRESH  = 0.4

# ── Classifier ────────────────────────────────────────────────────────────────
MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          'model', 'pose_classifier.pt')
_MEAN = [0.485, 0.456, 0.406]
_STD  = [0.229, 0.224, 0.225]
infer_tf = transforms.Compose([
    transforms.Resize(256),
    transforms.CenterCrop(224),
    transforms.ToTensor(),
    transforms.Normalize(_MEAN, _STD),
])
# ─────────────────────────────────────────────────────────────────────────────


# ── Skeleton stability (gaussian skeleton) ────────────────────────────────────
def _frame_distance(a, b):
    total = 0.0
    for la, lb in zip(a, b):
        dx, dy, dz = la['x'] - lb['x'], la['y'] - lb['y'], la['z'] - lb['z']
        total += math.sqrt(dx * dx + dy * dy + dz * dz)
    return total


def _stability_score(frames, idx, N, sigma):
    """Gaussian-weighted sum of distances from frame idx to its N neighbours."""
    score = 0.0
    for k in range(-N, N + 1):
        if k == 0:
            continue
        j = idx + k
        if 0 <= j < len(frames):
            score += _frame_distance(frames[idx], frames[j]) * math.exp(-k * k / (2.0 * sigma * sigma))
    return score


def most_stable_frame(frames, N=STABILITY_N, sigma=STABILITY_SIGMA):
    if len(frames) < 2 * N + 1:
        return len(frames) // 2
    scores = [_stability_score(frames, i, N, sigma) for i in range(N, len(frames) - N)]
    return N + scores.index(min(scores))


def _lm_valid(norm_lm, idx):
    if idx >= len(norm_lm):
        return False
    lm = norm_lm[idx]
    return (lm.get('presence', 0) >= PRESENCE_THRESH and
            lm.get('visibility', 0) >= VISIBILITY_THRESH)


def _is_valid_skel_frame(norm_lm):
    return bool(norm_lm) and all(_lm_valid(norm_lm, i) for i in REQUIRED_LANDMARKS if i < len(norm_lm))


def load_classifier(model_path, device):
    checkpoint = torch.load(model_path, map_location=device)
    classes = checkpoint['classes']
    model = models.mobilenet_v3_large(weights=None)
    model.classifier[-1] = nn.Linear(model.classifier[-1].in_features, len(classes))
    model.load_state_dict(checkpoint['state_dict'])
    model.to(device).eval()
    return model, classes


class StateManager:
    def __init__(self):
        self.lock = threading.Lock()

        # latest frames: annotated drives the live feed, clean drives classification
        self.latest_annotated = None
        self.latest_clean     = None

        # current cycle — each cycle is a tracking phase followed by a results
        # phase. During 'tracking' we buffer skeletons; during 'results' tracking
        # is frozen and the UI shows the captured frame / skeleton / move.
        self.cycle        = 0
        self.phase        = 'tracking'
        self.phase_start  = time.time()
        self.buffer       = []      # list of (norm_lm, clean_bgr) this cycle
        self.current_skel = None    # most-stable skeleton so far this cycle

        # latest result (shown in UI during the results phase and after)
        self.result_id      = 0     # bumps once the classifier produces a result
        self.result_pending = False # in results phase but classify not done yet
        self.prev_skel      = None
        self.prev_had_human = None
        self.prev_move      = None
        self.prev_conf      = None
        self.prev_met       = None  # whether last result met the confidence threshold
        self.captured_jpg   = None  # clean frame that was classified, JPEG bytes

        # live confidence threshold (0..1). Below this the move is shown but not
        # published to the controller. Adjustable via the UI slider (/threshold).
        self.conf_threshold = 0.5

        # classifier
        self.device = (
            torch.device('cuda') if torch.cuda.is_available() else
            torch.device('mps')  if torch.backends.mps.is_available() else
            torch.device('cpu')
        )
        self.model, self.classes = load_classifier(MODEL_PATH, self.device)
        rospy.loginfo('[WebServer] classifier loaded on %s — classes: %s',
                      self.device, self.classes)

        # set by ros_main once the publishers exist
        self.body_pub = None
        self.kill_pub = None
        self.killed   = False

    # ── ingestion ─────────────────────────────────────────────────────────────
    @staticmethod
    def _ros_to_bgr(ros_image):
        frame = np.ndarray(
            (ros_image.height, ros_image.width, 3),
            dtype=np.uint8, buffer=ros_image.data,
        ).copy()
        if getattr(ros_image, 'encoding', '') == 'rgb8':
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        return frame

    def on_annotated_image(self, ros_image):
        frame = self._ros_to_bgr(ros_image)
        with self.lock:
            self.latest_annotated = frame

    def on_clean_image(self, ros_image):
        frame = self._ros_to_bgr(ros_image)
        with self.lock:
            self.latest_clean = frame

    def on_landmarks(self, norm_lm):
        to_classify = None  # (skeleton, frame, cycle) handled outside the lock

        with self.lock:
            now = time.time()
            phase_elapsed = now - self.phase_start

            if self.phase == 'tracking':
                if phase_elapsed >= TRACKING_DURATION:
                    if self.buffer:
                        # ── end of tracking → classify, enter results phase ──
                        idx = most_stable_frame([b[0] for b in self.buffer])
                        skel, frame = self.buffer[idx]
                        to_classify = (skel, frame, self.cycle)
                        self.result_pending = True
                        self.phase        = 'results'
                        self.phase_start  = now
                    else:
                        # no human seen → skip results, rescan immediately
                        self.cycle       += 1
                        self.phase_start  = now
                    self.buffer       = []
                    self.current_skel = None
                else:
                    # ── ingest this frame ────────────────────────────────────
                    if _is_valid_skel_frame(norm_lm) and self.latest_clean is not None:
                        self.buffer.append((norm_lm, self.latest_clean.copy()))
                        self.current_skel = self.buffer[most_stable_frame([b[0] for b in self.buffer])][0]

            else:  # results phase — tracking is frozen; just wait it out
                if phase_elapsed >= RESULTS_DURATION:
                    self.phase        = 'tracking'
                    self.phase_start  = now
                    self.cycle       += 1
                    self.buffer       = []
                    self.current_skel = None

        # ── classify the most-stable clean frame of the cycle that just ended ─
        if to_classify is not None:
            skel, frame, ended = to_classify
            move, conf = self.classify_frame(frame)
            ok, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            with self.lock:
                met = conf >= self.conf_threshold
                self.prev_skel      = skel
                self.prev_had_human = True
                self.prev_move      = move
                self.prev_conf      = conf
                self.prev_met       = met
                self.captured_jpg   = buf.tobytes() if ok else None
                self.result_id     += 1
                self.result_pending = False
            if met:
                rospy.loginfo('[WebServer] cycle %d → %s (%.1f%%)', ended, move, conf * 100)
                if self.body_pub is not None:
                    self.body_pub.publish(json.dumps(
                        {'cycle': ended, 'move': move, 'confidence': conf}
                    ))
            else:
                rospy.loginfo('[WebServer] cycle %d → %s (%.1f%%) below threshold — not published',
                              ended, move, conf * 100)

    def classify_frame(self, bgr):
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        tensor = infer_tf(PILImage.fromarray(rgb)).unsqueeze(0).to(self.device)
        with torch.no_grad():
            probs = torch.softmax(self.model(tensor), dim=1)[0]
        conf, idx = probs.max(0)
        return self.classes[idx.item()], conf.item()

    # ── readers for the web layer ────────────────────────────────────────────
    def snapshot(self):
        with self.lock:
            duration = TRACKING_DURATION if self.phase == 'tracking' else RESULTS_DURATION
            elapsed = min(max(time.time() - self.phase_start, 0.0), duration)
            return {
                'current_skeleton': self.current_skel,
                'prev_skeleton':    self.prev_skel,
                'prev_had_human':   self.prev_had_human,
                'has_capture':      self.captured_jpg is not None,
                'move':             self.prev_move,
                'confidence':       self.prev_conf,
                'cycle':            self.cycle,
                'result_id':        self.result_id,
                'result_pending':   self.result_pending,
                'phase':            self.phase,
                'phase_elapsed':    elapsed,
                'phase_duration':   duration,
                'threshold':        self.conf_threshold,
                'met':              self.prev_met,
                'killed':           self.killed,
            }

    def set_threshold(self, value):
        value = max(0.0, min(1.0, float(value)))
        with self.lock:
            self.conf_threshold = value
        return value

    def kill_all(self):
        """Tell every node to stop. Latched, so nodes started later still get it."""
        with self.lock:
            self.killed = True
        if self.kill_pub is not None:
            self.kill_pub.publish(Bool(data=True))
        rospy.logwarn('[WebServer] KILL issued — broadcast stop on %s', SHUTDOWN_TOPIC)

    def get_latest_bgr(self):
        with self.lock:
            return self.latest_annotated

    def get_captured_jpg(self):
        with self.lock:
            return self.captured_jpg


state = StateManager()
app = Flask(__name__)

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Pose Classifier</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:monospace;background:#0e0e0e;color:#ddd;min-height:100vh}
header{display:flex;align-items:center;gap:14px;padding:10px 18px;
       border-bottom:1px solid #222;background:#141414}
header h1{font-size:16px;color:#aaa;letter-spacing:.05em;margin-right:auto}
.badge{padding:3px 10px;border-radius:3px;font-size:12px;font-weight:bold;letter-spacing:.08em}
.cycle-badge{background:#1a237e;color:#9fa8da}
.move-badge{background:#1b5e20;color:#a5d6a7;text-transform:uppercase}
.cycle-progress{height:4px;width:100%;background:#1a1a1a;overflow:hidden}
#cycle-bar{height:100%;width:0;background:linear-gradient(90deg,#1a237e,#3949ab,#5c6bc0)}
#cycle-bar.results{background:linear-gradient(90deg,#1b5e20,#2e7d32,#43a047)}
.layout{display:flex;gap:10px;padding:10px}
.pane{background:#141414;border:1px solid #222;border-radius:5px;padding:10px}
.feed-pane{flex:1;min-width:0}
.skel-pane{width:265px;flex-shrink:0}
/* results stage: drop the progress bar + live stream, enlarge skeleton & result */
body.results-view .cycle-progress{display:none}
body.results-view .feed-pane{display:none}
body.results-view .skel-pane{width:auto;flex:1}
body.results-view .pane-title{font-size:13px}
.pane-title{font-size:11px;color:#555;text-transform:uppercase;letter-spacing:.1em;margin-bottom:8px}
img#feed,img#capture{width:100%;border-radius:3px;background:#000;display:block}
canvas.skel{width:100%;background:#0a0a0a;border-radius:3px;display:block}
.move-line{margin-top:8px;font-size:13px;color:#a5d6a7;text-align:center}
.move-line .conf{color:#666}
.move-line.rejected{color:#e57373}
.move-line .notsent{color:#e57373}
.thresh{display:flex;align-items:center;gap:8px;font-size:12px;color:#888}
.thresh input[type=range]{width:120px;accent-color:#3949ab}
.thresh #thresh-val{color:#9fa8da;font-weight:bold;min-width:34px;text-align:right}
.msg{display:flex;align-items:center;justify-content:center;height:130px;
     font-size:12px;color:#555;gap:5px;flex-wrap:wrap}
.msg.no-human{color:#b71c1c}
.dot{width:6px;height:6px;border-radius:50%;background:#333;flex-shrink:0;
     animation:pulse 1.1s ease-in-out infinite}
.dot:nth-child(2){animation-delay:.15s}.dot:nth-child(3){animation-delay:.3s}
@keyframes pulse{0%,100%{opacity:.3;transform:scale(.8)}50%{opacity:1;transform:scale(1.2)}}
@keyframes cycle-flash{0%{border-color:#388e3c;box-shadow:0 0 10px #388e3c}100%{border-color:#222;box-shadow:none}}
.cycle-flash{animation:cycle-flash 0.8s ease-out forwards}
#kill-btn{font-family:inherit;font-weight:bold;letter-spacing:.1em;cursor:pointer;
  padding:5px 14px;border-radius:3px;border:1px solid #b71c1c;background:#7f1313;
  color:#ffcdd2}
#kill-btn:hover{background:#b71c1c;color:#fff}
#kill-btn:disabled{opacity:.5;cursor:default}
#kill-banner{display:none;padding:8px 18px;background:#b71c1c;color:#fff;
  font-weight:bold;letter-spacing:.08em;text-align:center}
body.killed #kill-banner{display:block}
body.killed #kill-btn{background:#b71c1c;color:#fff}
</style>
</head>
<body>
<header>
  <h1>Pose Classifier</h1>
  <label class="thresh">
    confidence ≥
    <input type="range" id="thresh" min="0" max="100" value="50">
    <span id="thresh-val">50%</span>
  </label>
  <span id="move-badge" class="badge move-badge">—</span>
  <span id="cycle-badge" class="badge cycle-badge">cycle 0</span>
  <button id="kill-btn" type="button">KILL</button>
</header>
<div id="kill-banner">STOPPED — all nodes told to shut down</div>
<div class="cycle-progress"><div id="cycle-bar"></div></div>

<div class="layout">
  <div class="pane feed-pane">
    <div class="pane-title">Camera</div>
    <img id="feed" src="/feed" alt="camera feed">
  </div>
  <div class="pane skel-pane" id="live-pane">
    <div class="pane-title" id="live-title">Live Skeleton</div>
    <div id="live-box">
      <div class="msg"><span class="dot"></span><span class="dot"></span><span class="dot"></span><span>scanning…</span></div>
    </div>
  </div>
  <div class="pane skel-pane">
    <div class="pane-title">Classified Frame</div>
    <div id="prev-box">
      <div class="msg"><span>waiting for first cycle…</span></div>
    </div>
    <div id="move-line" class="move-line"></div>
  </div>
</div>

<script>
const CONN = [
  [0,1],[1,2],[2,3],[3,7],[0,4],[4,5],[5,6],[6,8],
  [9,10],[11,12],
  [11,13],[13,15],[15,17],[15,19],[15,21],[17,19],
  [12,14],[14,16],[16,18],[16,20],[16,22],[18,20],
  [11,23],[12,24],[23,24],
  [23,25],[25,27],[27,29],[27,31],[29,31],
  [24,26],[26,28],[28,30],[28,32],[30,32],
];

const LEFT_IDS  = new Set([1,2,3,7,13,15,17,19,21,23,25,27,29,31]);
const RIGHT_IDS = new Set([4,5,6,8,14,16,18,20,22,24,26,28,30,32]);
function connColor(a, b) {
  if (LEFT_IDS.has(a)  || LEFT_IDS.has(b))  return '#26a69a';
  if (RIGHT_IDS.has(a) || RIGHT_IDS.has(b)) return '#1565c0';
  return '#555';
}

function drawSkel(boxId, skel) {
  const box = document.getElementById(boxId);
  let cv = box.querySelector('canvas');
  if (!cv) {
    box.innerHTML = '<canvas class="skel"></canvas>';
    cv = box.querySelector('canvas');
  }
  const W = cv.offsetWidth || 245, H = Math.round(W * 1.4);
  cv.width = W; cv.height = H;
  const ctx = cv.getContext('2d');
  ctx.fillStyle = '#0a0a0a';
  ctx.fillRect(0, 0, W, H);
  const pad = 20;
  const pt = lm => [lm.x * (W - 2*pad) + pad, lm.y * (H - 2*pad) + pad];
  ctx.lineWidth = 1.5;
  for (const [a, b] of CONN) {
    if (a >= skel.length || b >= skel.length) continue;
    ctx.strokeStyle = connColor(a, b);
    ctx.beginPath();
    const [ax, ay] = pt(skel[a]), [bx, by] = pt(skel[b]);
    ctx.moveTo(ax, ay); ctx.lineTo(bx, by);
    ctx.stroke();
  }
  ctx.fillStyle = '#80cbc4';
  for (const lm of skel) {
    const [x, y] = pt(lm);
    ctx.beginPath(); ctx.arc(x, y, 2.5, 0, 2*Math.PI); ctx.fill();
  }
}

function showMsg(boxId, text, cls='') {
  document.getElementById(boxId).innerHTML =
    '<div class="msg ' + cls + '">' + text + '</div>';
}

const SPINNER = '<span class="dot"></span><span class="dot"></span><span class="dot"></span>';

let prevView = '';

// ── live phase progress ───────────────────────────────────────────────────
// Each cycle has two phases: SCAN (tracking) then RESULT (frozen display).
// Anchor each SSE tick to the local clock, then interpolate with rAF so the
// bar fills smoothly between the 0.5 s server ticks and self-corrects on each.
let curCycle = 0;
let curPhase = 'tracking';
let phaseDuration = 5;
let tickElapsed = 0;
let tickAt = performance.now();
const cycleBar = document.getElementById('cycle-bar');
const cycleBadge = document.getElementById('cycle-badge');

// ── confidence threshold slider ───────────────────────────────────────────
const thresh = document.getElementById('thresh');
const threshVal = document.getElementById('thresh-val');
let threshInit = false;  // sync slider from server once on first SSE tick

function showThresh() { threshVal.textContent = thresh.value + '%'; }
thresh.addEventListener('input', showThresh);
thresh.addEventListener('change', function() {
  fetch('/threshold?value=' + (thresh.value / 100), {method: 'POST'});
});

// ── kill button ───────────────────────────────────────────────────────────
const killBtn = document.getElementById('kill-btn');
function markKilled() {
  document.body.classList.add('killed');
  killBtn.disabled = true;
}
killBtn.addEventListener('click', function() {
  if (!confirm('Stop ALL nodes? This shuts down the robot processes.')) return;
  fetch('/kill', {method: 'POST'});
  markKilled();
});

// track phase transitions so we can restart the live stream on re-entry
let lastPhase = null;

function animateCycle() {
  const elapsed = tickElapsed + (performance.now() - tickAt) / 1000;
  const p = Math.max(0, Math.min(1, elapsed / phaseDuration));
  cycleBar.style.width = (p * 100) + '%';
  const remain = Math.max(0, phaseDuration - elapsed);
  const label = curPhase === 'results' ? 'result' : 'scan';
  cycleBadge.textContent = 'cycle ' + curCycle + ' · ' + label + ' ' + remain.toFixed(1) + 's';
  requestAnimationFrame(animateCycle);
}
requestAnimationFrame(animateCycle);

const es = new EventSource('/events');
es.onmessage = function(ev) {
  const d = JSON.parse(ev.data);
  const isResults = d.phase === 'results';

  curCycle = d.cycle;
  curPhase = d.phase;
  if (d.phase_duration) phaseDuration = d.phase_duration;
  tickElapsed = d.phase_elapsed || 0;
  tickAt = performance.now();

  if (d.killed) markKilled();

  // sync the slider to the server's threshold once on connect
  if (!threshInit && d.threshold != null) {
    threshInit = true;
    thresh.value = Math.round(d.threshold * 100);
    showThresh();
  }

  // restart the MJPEG live stream when re-entering tracking — the feed is
  // display:none during results, which can stall the stream in some browsers
  if (!isResults && lastPhase === 'results') {
    document.getElementById('feed').src = '/feed?t=' + Date.now();
  }
  lastPhase = d.phase;

  const pending = isResults && d.result_pending;

  cycleBar.classList.toggle('results', isResults);
  document.body.classList.toggle('results-view', isResults);
  document.getElementById('move-badge').textContent = (isResults && !pending && d.move) ? d.move : '—';

  // left skeleton pane: live while scanning, frozen stable skeleton in results
  document.getElementById('live-title').textContent = isResults ? 'Stable Skeleton' : 'Live Skeleton';
  if (pending) {
    showMsg('live-box', SPINNER + '<span>classifying…</span>');
  } else if (isResults) {
    if (d.prev_skeleton) drawSkel('live-box', d.prev_skeleton);
    else showMsg('live-box', 'no human detected', 'no-human');
  } else if (d.current_skeleton) {
    drawSkel('live-box', d.current_skeleton);
  } else {
    showMsg('live-box', SPINNER + '<span>scanning…</span>');
  }

  // results pane — rebuild DOM only when what it should show actually changes.
  // While tracking we deliberately hide the previous classification.
  let view;
  if (!isResults)                     view = 'tracking';
  else if (pending)                   view = 'pending';
  else if (d.has_capture)             view = 'cap-' + d.result_id;
  else if (d.prev_had_human === false) view = 'nohuman-' + d.result_id;
  else                                view = 'waiting';

  if (view !== prevView) {
    prevView = view;
    const moveLine = document.getElementById('move-line');
    if (view === 'tracking') {
      showMsg('prev-box', SPINNER + '<span>scanning…</span>');
      moveLine.innerHTML = '';
    } else if (view === 'pending') {
      showMsg('prev-box', SPINNER + '<span>classifying…</span>');
      moveLine.innerHTML = '';
    } else if (d.has_capture) {
      const pane = document.getElementById('live-pane');
      pane.classList.remove('cycle-flash');
      void pane.offsetWidth;  // force reflow so re-adding the class restarts the animation
      pane.classList.add('cycle-flash');
      pane.addEventListener('animationend', () => pane.classList.remove('cycle-flash'), {once: true});
      document.getElementById('prev-box').innerHTML =
        '<img id="capture" src="/capture?c=' + d.result_id + '" alt="classified frame">';
      const conf = (d.confidence != null) ? ' <span class="conf">(' + (d.confidence*100).toFixed(0) + '%)</span>' : '';
      moveLine.classList.toggle('rejected', d.met === false);
      if (d.met === false) {
        moveLine.innerHTML = (d.move || '?') + conf +
          '<br><span class="notsent">below threshold — not sent</span>';
      } else {
        moveLine.innerHTML = d.move ? (d.move + conf) : '';
      }
    } else if (d.prev_had_human === false) {
      showMsg('prev-box', 'no human detected', 'no-human');
      moveLine.innerHTML = '';
    } else {
      showMsg('prev-box', 'waiting for first cycle…');
      moveLine.innerHTML = '';
    }
  }
};
es.onerror = function() {
  showMsg('live-box', 'DISCONNECTED');
};
</script>
</body>
</html>
"""


@app.route('/')
def index():
    return render_template_string(HTML)


@app.route('/feed')
def video_feed():
    def generate():
        while True:
            frame = state.get_latest_bgr()
            if frame is not None:
                ok, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
                if ok:
                    yield (
                        b'--frame\r\n'
                        b'Content-Type: image/jpeg\r\n\r\n' +
                        buf.tobytes() +
                        b'\r\n'
                    )
            time.sleep(0.04)
    return Response(
        generate(),
        mimetype='multipart/x-mixed-replace; boundary=frame',
    )


@app.route('/capture')
def capture():
    jpg = state.get_captured_jpg()
    if jpg is None:
        return Response(status=204)
    return Response(jpg, mimetype='image/jpeg')


@app.route('/threshold', methods=['POST'])
def set_threshold():
    raw = request.args.get('value', request.form.get('value'))
    try:
        value = state.set_threshold(raw)
    except (TypeError, ValueError):
        return Response('bad value', status=400)
    return Response(json.dumps({'threshold': value}), mimetype='application/json')


@app.route('/kill', methods=['POST'])
def kill():
    state.kill_all()
    return Response(json.dumps({'killed': True}), mimetype='application/json')


@app.route('/events')
def sse():
    def generate():
        while True:
            data = state.snapshot()
            yield 'data: ' + json.dumps(data) + '\n\n'
            time.sleep(0.5)
    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


def ros_main():
    rospy.init_node('pose_web_server', anonymous=False)

    state.body_pub = rospy.Publisher('/body_commands', String, queue_size=1)
    # latched so any node that subscribes after a kill still receives the stop
    state.kill_pub = rospy.Publisher(SHUTDOWN_TOPIC, Bool, queue_size=1, latch=True)

    def landmarks_cb(msg):
        try:
            payload = json.loads(msg.data)
            state.on_landmarks(payload.get('norm_landmarks', []))
        except Exception as e:
            rospy.logwarn('[WebServer] bad landmarks msg: %s' % e)

    rospy.Subscriber('/stable_gest/landmarks',       String, landmarks_cb)
    rospy.Subscriber('/stable_gest/image_annotated', Image,  state.on_annotated_image)
    rospy.Subscriber('/stable_gest/image_clean',     Image,  state.on_clean_image)
    rospy.loginfo('[WebServer] subscribed to /stable_gest/ — publishing /body_commands')
    rospy.spin()


if __name__ == '__main__':
    import sys
    import argparse
    sys.stdout = open(sys.stdout.fileno(), mode='w', buffering=1)

    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=WEB_PORT)
    args = parser.parse_args()

    def run_flask():
        try:
            app.run(host='0.0.0.0', port=args.port, threaded=True, use_reloader=False)
        except OSError as e:
            print('[WebServer] ERROR: %s' % e, flush=True)
            print('[WebServer] usage: python3 webserver.py [--port PORT]', flush=True)
            import os as _os; _os._exit(1)

    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print('[WebServer] http://0.0.0.0:%d' % args.port, flush=True)

    ros_main()
