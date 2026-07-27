// REST + audio helpers used by the demo state machine.
//
// Everything here is a plain async function (no React) so the pipeline runner in
// useDemoMachine can `await` each step in sequence — this is what keeps the
// 3-2-1 countdown locked to the speaker audio and the camera-click held until
// /classify returns.

import { ACTION_WS, SPEAKER_BASE } from './config'
import { getFeaturesBase, getPiBase, getRobotBase, getRobotConfig, getSimBase } from './robotConfig'
import type { LegMode } from './robotConfig'

/** One servo target: Hiwonder id + pulse (0–1000) + move time. */
export interface ServoCommand {
  servo_id: number
  position: number
  duration_ms: number
}

/** Result of retargeting the user's pose (landmarks → robot joints). Replaces
 *  the old MobileNetV3 ClassifyResult — no class name, no probabilities. */
export interface MapFeaturesResult {
  /** False when the hips aren't visible: no arm retargeting, caller should retake. */
  poseDetected: boolean
  /** Human-readable reason to show when poseDetected is false. */
  detail: string | null
  commands: ServoCommand[]
  imageB64: string | null
  /** Which leg strategy the server used for this call. */
  legMode: LegMode
  /** In 'classify' leg mode, the recognized pose class; null otherwise. */
  poseClass: string | null
}

export interface ActionResult {
  transcript: string
  content: string
  hasAction: boolean
  satisfied?: boolean | null
}

// ── Speaker (Mac :5002) — resolves only after speech finishes ─────────────────
export async function speak(opts: { script?: string; text?: string }): Promise<void> {
  const res = await fetch(`${SPEAKER_BASE}/speak`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(opts),
  })
  if (!res.ok) throw new Error(`speak failed: ${res.status}`)
}

// Stop any in-progress speech immediately (tab closed / demo restarted).
// Best-effort: a failure here must never block teardown. `keepalive` lets the
// request survive a page unload so a closing tab still silences Coral.
export async function killSpeech(): Promise<void> {
  try {
    await fetch(`${SPEAKER_BASE}/kill`, { method: 'POST', keepalive: true })
  } catch {
    /* ignore */
  }
}

// ── Robot server (Pi :9000) ───────────────────────────────────────────────────
export async function motion(name: string, globalDuration?: number): Promise<void> {
  const res = await fetch(`${getRobotBase()}/motion`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, global_duration: globalDuration ?? null }),
  })
  if (!res.ok) throw new Error(`motion failed: ${res.status}`)
}

// Retarget the user's current pose to robot servo commands. Hits the vision
// server directly (it owns the live landmarks); the caller executes the returned
// commands via move(). Also returns the frame the pose was read from, for the UI.
export async function mapFeatures(legMode?: LegMode): Promise<MapFeaturesResult> {
  // Default to the live-toggled leg mode from the shared robot config.
  const mode = legMode ?? getRobotConfig().legMode
  const url = `${getFeaturesBase()}/map-features?leg_mode=${encodeURIComponent(mode)}`
  const res = await fetch(url, { method: 'POST' })
  if (!res.ok) {
    // Surface the server's actual failure reason (e.g. a Python exception
    // message) instead of just the status code — FastAPI puts it in `detail`.
    const body = await res.json().catch(() => null)
    throw new Error(`map-features failed: ${res.status} ${body?.detail ?? ''}`.trim())
  }
  const data = await res.json()
  return {
    poseDetected: data.pose_detected !== false,
    detail: data.detail ?? null,
    commands: Array.isArray(data.commands) ? data.commands : [],
    imageB64: data.image_b64 ?? null,
    legMode: (data.leg_mode ?? mode) as LegMode,
    poseClass: data.pose_class ?? null,
  }
}

// Toggle the knee-bend/hip-yaw debug angle arcs drawn on every live frame by
// the Mac vision server (see pose_estimator._draw_bucket_angle_arcs). Applies
// immediately, no restart needed. Best-effort like setRobotState — in
// hardware mode this endpoint doesn't exist on the Pi, so a failure here
// shouldn't block the UI toggle from flipping locally.
export async function setAngleArcsEnabled(enabled: boolean): Promise<void> {
  try {
    await fetch(`${getFeaturesBase()}/settings/angle-arcs?enabled=${enabled}`, {
      method: 'POST',
    })
  } catch {
    /* ignore */
  }
}

// Toggle the dynamic fall check on the robot base server (StabilityChecker —
// see collision_checked_targets in server.py). Applies immediately, no
// restart needed. Best-effort like setAngleArcsEnabled: a failure here
// shouldn't block the UI toggle from flipping locally.
export async function setFallCheckEnabled(enabled: boolean): Promise<void> {
  try {
    await fetch(`${getRobotBase()}/settings/fall-check?enabled=${enabled}`, {
      method: 'POST',
    })
  } catch {
    /* ignore */
  }
}

// Persist whether the native MuJoCo window opens the next time the base server
// starts (POST /settings/mujoco-viewer). Unlike the toggles above this cannot
// apply now — the window has to be opened at process start — so it only writes
// the preference. Best-effort all the same.
export async function setMujocoViewerOnLaunch(enabled: boolean): Promise<void> {
  try {
    await fetch(`${getRobotBase()}/settings/mujoco-viewer?enabled=${enabled}`, {
      method: 'POST',
    })
  } catch {
    /* ignore */
  }
}

// Safety-check outcome attached to /move responses. `fallBlocked` means the
// dynamics shadow-check saw the robot topple, so the server executed 0% of
// the move; `collisionClamped` means the kinematic checker pulled the motion
// back to `safeFraction` of the commanded target.
export interface MoveSafety {
  fallBlocked: boolean
  collisionClamped: boolean
  safeFraction: number
  badPairs: string[]
}

export interface MoveResult {
  executed: boolean
  safety: MoveSafety
}

const SAFE_MOVE: MoveSafety = {
  fallBlocked: false,
  collisionClamped: false,
  safeFraction: 1,
  badPairs: [],
}

// Drive the robot/sim with raw servo commands (from mapFeatures). No-op safe if
// the command list is empty. Returns the server's safety verdict so callers
// (the refined demo) can report a blocked move to the user.
export async function move(
  commands: ServoCommand[],
  simOnly = getRobotConfig().simOnly,
): Promise<MoveResult> {
  if (commands.length === 0) return { executed: false, safety: SAFE_MOVE }
  const res = await fetch(`${getRobotBase()}/move`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ moves: commands, sim_only: simOnly }),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(`move failed: ${res.status} ${body?.detail ?? ''}`.trim())
  }
  const data = await res.json().catch(() => null)
  const s = data?.safety
  return {
    executed: data?.status !== 'blocked',
    safety: s
      ? {
          fallBlocked: s.fall_blocked === true,
          collisionClamped: s.collision_clamped === true,
          safeFraction: typeof s.safe_fraction === 'number' ? s.safe_fraction : 1,
          badPairs: Array.isArray(s.bad_pairs) ? s.bad_pairs : [],
        }
      : SAFE_MOVE,
  }
}

// Apply a raw {joint: hardware_pulse} pose to the sim (testing tool). Pulses are
// the same hardware units authored in motions.py; the server converts them to sim
// radians. Sim only — always hits the main Mac server, not the Pi (getSimBase
// ignores the sim/hardware toggle; the Pi has no /set-pose).
// `skipCollisionCheck` applies the pose exactly as authored, bypassing the
// server's collision shadow-roll (joint limits still clamp).
export async function setPose(
  pulses: Record<string, number>,
  skipCollisionCheck = false,
): Promise<{ applied: string[]; skipped: string[] }> {
  const res = await fetch(`${getSimBase()}/set-pose`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pulses, skip_collision_check: skipCollisionCheck }),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(`set-pose failed: ${res.status} ${body?.detail ?? ''}`.trim())
  }
  const data = await res.json()
  return { applied: data.applied ?? [], skipped: data.skipped ?? [] }
}

/** joint name → Hiwonder servo id (mirrors the Pi server's SERVO_ID). */
export const SERVO_ID: Record<string, number> = {
  l_ank_roll: 1, r_ank_roll: 2,
  l_ank_pitch: 3, r_ank_pitch: 4,
  l_knee: 5, r_knee: 6,
  l_hip_pitch: 7, r_hip_pitch: 8,
  l_hip_roll: 9, r_hip_roll: 10,
  l_hip_yaw: 11, r_hip_yaw: 12,
  l_sho_pitch: 13, r_sho_pitch: 14,
  l_sho_roll: 15, r_sho_roll: 16,
  l_el_pitch: 17, r_el_pitch: 18,
  l_el_yaw: 19, r_el_yaw: 20,
  l_gripper: 21, r_gripper: 22,
  head_pan: 23, head_tilt: 24,
}

// Play a raw {joint: hardware_pulse} pose on the physical robot via the Pi's
// minimal /move endpoint (testing tool). Pulses go to the hardware as-is (the
// Pi clamps to each servo's safe range); the response returns only after the
// motion finishes. Always hits the Pi, regardless of the sim/hardware toggle.
export async function movePulses(
  pulses: Record<string, number>,
  durationMs: number,
): Promise<{ count: number }> {
  const commands: ServoCommand[] = Object.entries(pulses)
    .filter(([name]) => SERVO_ID[name] !== undefined)
    .map(([name, position]) => ({
      servo_id: SERVO_ID[name],
      position,
      duration_ms: durationMs,
    }))
  const res = await fetch(`${getPiBase()}/move`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(commands),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(`robot move failed: ${res.status} ${body?.detail ?? ''}`.trim())
  }
  const data = await res.json().catch(() => null)
  return { count: data?.count ?? commands.length }
}

export async function watchForAction(timeoutS: number): Promise<{ detected: boolean }> {
  const res = await fetch(`${getRobotBase()}/watch-for-action?timeout=${timeoutS}`)
  if (!res.ok) throw new Error(`watch-for-action failed: ${res.status}`)
  const data = await res.json()
  return { detected: !!data.detected }
}

export async function setRobotState(mode: string): Promise<void> {
  // Best-effort lock/unlock — never let a state toggle abort the demo.
  try {
    await fetch(`${getRobotBase()}/state`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode }),
    })
  } catch {
    /* ignore */
  }
}

// ── Vision subject selection (multi-person re-ID lock) ───────────────────────
export type SubjectSelectionState = 'idle' | 'selecting' | 'selected' | 'searching'

export interface SubjectSelectionUpdate {
  state: SubjectSelectionState
  selectedSubjectId: string | null
  subjectsCount: number
  // Max hold_progress (0-1) across all current candidates — drives the modal's
  // "raise-and-hold" progress bar.
  holdProgress: number
}

export async function startSubjectSelection(): Promise<void> {
  await fetch(`${getFeaturesBase()}/subject-selection/start`, { method: 'POST' })
}

// Best-effort — teardown must not block. keepalive lets the request survive a
// page unload so leaving the demo still returns the vision server to single-
// person mode.
export async function stopSubjectSelection(): Promise<void> {
  try {
    await fetch(`${getFeaturesBase()}/subject-selection/stop`, {
      method: 'POST',
      keepalive: true,
    })
  } catch {
    /* ignore */
  }
}

export async function resetSubjectSelection(): Promise<void> {
  try {
    await fetch(`${getFeaturesBase()}/subject-selection/reset`, { method: 'POST' })
  } catch {
    /* ignore */
  }
}

// Subscribe to pose updates from the vision server and surface only the
// subject-selection fields. Auto-reconnects on drop until the returned cleanup
// is called.
export function subscribeSubjectSelection(
  onUpdate: (u: SubjectSelectionUpdate) => void,
): () => void {
  const wsUrl = getFeaturesBase().replace(/^http/, 'ws') + '/ws/pose'
  let ws: WebSocket | null = null
  let retry: ReturnType<typeof setTimeout> | null = null
  let closed = false

  const open = () => {
    if (closed) return
    ws = new WebSocket(wsUrl)
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.type !== 'pose_update') return
        const subjects = Array.isArray(data.subjects) ? data.subjects : []
        let hold = 0
        for (const s of subjects) {
          const p = typeof s?.hold_progress === 'number' ? s.hold_progress : 0
          if (p > hold) hold = p
        }
        onUpdate({
          state: (data.selection_state ?? 'idle') as SubjectSelectionState,
          selectedSubjectId: data.selected_subject_id ?? null,
          subjectsCount: subjects.length,
          holdProgress: hold,
        })
      } catch {
        /* ignore malformed frames */
      }
    }
    ws.onclose = () => {
      if (closed) return
      retry = setTimeout(open, 1500)
    }
    ws.onerror = () => {
      try { ws?.close() } catch { /* ignore */ }
    }
  }

  open()
  return () => {
    closed = true
    if (retry) clearTimeout(retry)
    try { ws?.close() } catch { /* ignore */ }
  }
}

// Snap the sim (and, in robot mode, animate the hardware) back to the stand
// pose via the "reset" primitive in mujoco_sim.COMMAND_MAP.
export async function resetPose(): Promise<void> {
  const res = await fetch(`${getRobotBase()}/command`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ command: 'reset' }),
  })
  if (!res.ok) throw new Error(`reset failed: ${res.status}`)
}

// ── Audio capture (one utterance, auto-stop on silence) ───────────────────────
// Compact VAD: wait indefinitely for speech to start, then record until ~1.2s
// of trailing silence, or `maxMs` after speech began (whichever comes first).
// `maxMs` bounds utterance length only — silent waiting time is unbounded so
// the demo doesn't fire the WebSocket timeout on a user who's still thinking.
//
// The caller may pass an `AbortSignal` to release the mic immediately (e.g.
// when the user clicks a chip mid-listen or restarts the demo). Every exit
// path — success, error, or abort — settles exactly once and tears down the
// MediaStream + AudioContext, so a lingering mic acquisition can't wedge the
// next capture on browsers that block concurrent getUserMedia calls.
export async function captureUtterance(
  opts: {
    silenceMs?: number
    maxMs?: number
    threshold?: number
    onLevel?: (rms: number) => void
    signal?: AbortSignal
  } = {},
): Promise<Blob> {
  const { silenceMs = 1200, maxMs = 12000, threshold = 10, onLevel, signal } = opts

  if (signal?.aborted) {
    throw new DOMException('captureUtterance aborted', 'AbortError')
  }

  const stream = await navigator.mediaDevices.getUserMedia({ audio: true })

  // Caller may have aborted while getUserMedia was resolving — release the mic
  // we just acquired rather than start recording into a dead session.
  if (signal?.aborted) {
    stream.getTracks().forEach((t) => t.stop())
    throw new DOMException('captureUtterance aborted', 'AbortError')
  }

  const ctx = new AudioContext()
  const source = ctx.createMediaStreamSource(stream)
  const analyser = ctx.createAnalyser()
  analyser.fftSize = 512
  source.connect(analyser)

  const recorder = new MediaRecorder(stream)
  const chunks: Blob[] = []
  recorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data) }

  const buf = new Uint8Array(analyser.fftSize)
  let speechStartedAt: number | null = null
  let silenceSince: number | null = null

  const cleanup = () => {
    try { stream.getTracks().forEach((t) => t.stop()) } catch { /* ignore */ }
    try { ctx.close().catch(() => {}) } catch { /* ignore */ }
  }

  return new Promise<Blob>((resolve, reject) => {
    let settled = false
    let stopFallback: ReturnType<typeof setTimeout> | null = null

    const finalizeSuccess = () => {
      if (settled) return
      settled = true
      if (stopFallback) { clearTimeout(stopFallback); stopFallback = null }
      cleanup()
      resolve(new Blob(chunks, { type: 'audio/webm' }))
    }
    const finalizeError = (err: Error) => {
      if (settled) return
      settled = true
      if (stopFallback) { clearTimeout(stopFallback); stopFallback = null }
      try { if (recorder.state === 'recording') recorder.stop() } catch { /* ignore */ }
      cleanup()
      reject(err)
    }
    // Ask the recorder to flush + emit onstop; if the browser never fires
    // onstop (rare, but observed), the fallback resolves with what we have so
    // the caller isn't wedged forever.
    const requestStop = () => {
      if (settled) return
      try { recorder.stop() } catch (e) {
        finalizeError(new Error(`recorder.stop failed: ${e instanceof Error ? e.message : String(e)}`))
        return
      }
      stopFallback = setTimeout(() => { finalizeSuccess() }, 2000)
    }

    recorder.onstop = () => finalizeSuccess()
    recorder.onerror = (e) => {
      const inner = (e as unknown as { error?: { message?: string } }).error?.message
      finalizeError(new Error(`MediaRecorder error: ${inner ?? 'unknown'}`))
    }

    // Track ended = mic revoked, unplugged, or OS took the device away.
    stream.getTracks().forEach((t) => {
      t.addEventListener('ended', () => {
        finalizeError(new Error('microphone track ended unexpectedly'))
      })
    })

    const onAbort = () => finalizeError(new DOMException('captureUtterance aborted', 'AbortError'))
    if (signal) signal.addEventListener('abort', onAbort, { once: true })

    try {
      recorder.start()
    } catch (err) {
      finalizeError(new Error(`recorder.start failed: ${err instanceof Error ? err.message : String(err)}`))
      return
    }

    const tick = () => {
      if (settled) return
      if (recorder.state !== 'recording') { finalizeSuccess(); return }
      try {
        analyser.getByteTimeDomainData(buf)
      } catch (err) {
        finalizeError(new Error(`analyser read failed: ${err instanceof Error ? err.message : String(err)}`))
        return
      }
      let sum = 0
      for (let i = 0; i < buf.length; i++) { const v = buf[i] - 128; sum += v * v }
      const rms = Math.sqrt(sum / buf.length)
      try { onLevel?.(rms) } catch { /* callback errors are the caller's problem, not ours */ }
      const now = performance.now()
      if (rms > threshold) {
        if (speechStartedAt == null) speechStartedAt = now
        silenceSince = null
      } else if (speechStartedAt != null) {
        if (silenceSince == null) silenceSince = now
        else if (now - silenceSince > silenceMs) { requestStop(); return }
      }
      if (speechStartedAt != null && now - speechStartedAt > maxMs) { requestStop(); return }
      requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
  })
}

// ── Audio → transcript only (no LLM) over the existing /ws pipeline ──────────
// Resolves as soon as Whisper returns the transcription text. The server will
// continue on to the LLM but we close the socket early — the robot won't move.
export function sendAudioForTranscript(blob: Blob, timeoutMs = 30000): Promise<string> {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(ACTION_WS)
    const timer = setTimeout(() => { ws.close(); reject(new Error('transcription timed out')) }, timeoutMs)

    ws.onopen = () => {
      const reader = new FileReader()
      reader.onloadend = () => {
        const base64 = (reader.result as string).split(',')[1]
        ws.send(JSON.stringify({ type: 'audio', data: base64, format: 'webm' }))
      }
      reader.readAsDataURL(blob)
    }
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      if (data.type === 'transcription') {
        clearTimeout(timer)
        ws.close()
        resolve(data.text ?? '')
      }
      // chat_response intentionally ignored
    }
    ws.onerror = () => { clearTimeout(timer); reject(new Error('transcription ws error')) }
  })
}

// ── Audio → action over the existing server.py /ws pipeline ───────────────────
// Sends the recorded utterance to the Whisper + LLM motion planner and waits for
// the chat_response. Non-empty `waypoints` means the model produced an action;
// empty means it asked for clarification (or nothing was understood).
export function sendAudioForAction(
  blob: Blob,
  timeoutMs = 30000,
  onActionStarted?: () => void,
): Promise<ActionResult> {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(ACTION_WS)
    let transcript = ''
    const timer = setTimeout(() => { ws.close(); reject(new Error('audio-to-action timed out')) }, timeoutMs)

    ws.onopen = async () => {
      const reader = new FileReader()
      reader.onloadend = () => {
        const base64 = (reader.result as string).split(',')[1]
        ws.send(JSON.stringify({ type: 'audio', data: base64, format: 'webm' }))
      }
      reader.readAsDataURL(blob)
    }
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      if (data.type === 'transcription') {
        transcript = data.text ?? ''
      } else if (data.type === 'action_started') {
        onActionStarted?.() // robot execution has begun server-side
      } else if (data.type === 'chat_response') {
        clearTimeout(timer)
        ws.close()
        const waypoints = Array.isArray(data.waypoints) ? data.waypoints : []
        resolve({ transcript, content: data.content ?? '', hasAction: waypoints.length > 0, satisfied: data.satisfied ?? null })
      }
    }
    ws.onerror = () => { clearTimeout(timer); reject(new Error('audio-to-action ws error')) }
  })
}

// ── Persistent action session (multi-turn refinement) ────────────────────────
// Each call to sendAudioForAction / sendTextForAction opens a fresh WebSocket,
// which makes the server spin up a new HierarchicalMemory + Langfuse session —
// so the LLM never sees prior turns during an iterative pose refinement. An
// ActionSession keeps one socket open across the whole ADJUST loop so memory
// (and the Langfuse trace) span every turn.
export interface ActionSession {
  sendAudio(blob: Blob, timeoutMs?: number): Promise<ActionResult>
  sendText(
    text: string,
    intentType?: 'motion' | 'conversation' | 'immediate' | 'clarification',
    description?: string,
    timeoutMs?: number,
  ): Promise<ActionResult>
  close(): void
}

export function openActionSession(sessionId?: string): ActionSession {
  const wsUrl = sessionId ? `${ACTION_WS}?session_id=${encodeURIComponent(sessionId)}` : ACTION_WS
  const ws = new WebSocket(wsUrl)

  const openPromise = new Promise<void>((resolve, reject) => {
    const cleanup = () => {
      ws.removeEventListener('open', onOpen)
      ws.removeEventListener('error', onError)
    }
    const onOpen = () => { cleanup(); resolve() }
    const onError = () => { cleanup(); reject(new Error('action session ws failed to open')) }
    ws.addEventListener('open', onOpen)
    ws.addEventListener('error', onError)
  })

  type Pending = {
    transcript: string
    resolve: (r: ActionResult) => void
    reject: (e: Error) => void
    timer: ReturnType<typeof setTimeout>
  }
  let pending: Pending | null = null
  let closed = false

  const failPending = (err: Error) => {
    if (pending) {
      clearTimeout(pending.timer)
      pending.reject(err)
      pending = null
    }
  }

  ws.addEventListener('message', (event) => {
    if (!pending) return
    const data = JSON.parse(event.data)
    if (data.type === 'transcription') {
      pending.transcript = data.text ?? ''
    } else if (data.type === 'chat_response') {
      const p = pending
      pending = null
      clearTimeout(p.timer)
      const waypoints = Array.isArray(data.waypoints) ? data.waypoints : []
      p.resolve({
        transcript: p.transcript,
        content: data.content ?? '',
        hasAction: waypoints.length > 0,
        satisfied: data.satisfied ?? null,
      })
    }
  })
  // Once the socket goes down, mark the session dead so subsequent send()
  // calls fail fast instead of writing to a closed WS (which either throws
  // or silently drops, leaving `pending` set and the next call stuck on 'busy').
  ws.addEventListener('close', () => {
    closed = true
    failPending(new Error('action session ws closed'))
  })
  ws.addEventListener('error', () => {
    closed = true
    failPending(new Error('action session ws error'))
  })

  const send = async (payload: object, timeoutMs: number, initialTranscript = ''): Promise<ActionResult> => {
    if (closed) throw new Error('action session already closed')
    if (pending) throw new Error('action session busy')
    await openPromise
    if (closed) throw new Error('action session already closed')
    return new Promise<ActionResult>((resolve, reject) => {
      const timer = setTimeout(() => {
        pending = null
        reject(new Error('action session timed out'))
      }, timeoutMs)
      pending = { transcript: initialTranscript, resolve, reject, timer }
      try {
        ws.send(JSON.stringify(payload))
      } catch (err) {
        clearTimeout(timer)
        pending = null
        reject(err instanceof Error ? err : new Error(String(err)))
      }
    })
  }

  return {
    async sendAudio(blob, timeoutMs = 30000) {
      const base64 = await blobToBase64(blob)
      return send({ type: 'audio', data: base64, format: 'webm' }, timeoutMs)
    },
    async sendText(text, intentType, description, timeoutMs = 30000) {
      // Server won't emit a 'transcription' frame for text; seed it locally so the
      // caller sees what they typed as the "transcript" for UI parity with audio.
      const payload: Record<string, unknown> = { type: 'chat', content: text }
      if (intentType) payload.intent_type = intentType
      if (description) payload.description = description
      if (intentType === 'motion') payload.sim_only = getRobotConfig().simOnly
      return send(payload, timeoutMs, text)
    },
    close() {
      closed = true
      failPending(new Error('action session closed'))
      try { ws.close() } catch { /* ignore */ }
    },
  }
}

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onloadend = () => {
      const s = reader.result as string
      resolve(s.split(',')[1] ?? '')
    }
    reader.onerror = () => reject(reader.error ?? new Error('blob read failed'))
    reader.readAsDataURL(blob)
  })
}

// ── Text → action over the existing server.py /ws pipeline ────────────────────
// Text-input equivalent of sendAudioForAction: sends a typed instruction straight
// to the LLM motion planner (skipping Whisper) and waits for the chat_response.
export function sendTextForAction(
  text: string,
  timeoutMs = 30000,
  onActionStarted?: () => void,
): Promise<ActionResult> {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(ACTION_WS)
    const timer = setTimeout(() => { ws.close(); reject(new Error('text-to-action timed out')) }, timeoutMs)

    ws.onopen = () => {
      ws.send(JSON.stringify({ type: 'chat', content: text }))
    }
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      if (data.type === 'action_started') {
        onActionStarted?.() // robot execution has begun server-side
      } else if (data.type === 'chat_response') {
        clearTimeout(timer)
        ws.close()
        const waypoints = Array.isArray(data.waypoints) ? data.waypoints : []
        resolve({ transcript: text, content: data.content ?? '', hasAction: waypoints.length > 0, satisfied: data.satisfied ?? null })
      }
    }
    ws.onerror = () => { clearTimeout(timer); reject(new Error('text-to-action ws error')) }
  })
}

// ── Misc ──────────────────────────────────────────────────────────────────────
export function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
}

// Intent classifier result from /classify-intent.
// The optional `name` field is populated for the `naming` intent when the user
// supplies a suggested pose name (e.g. "save this as my cool pose").
// `classifier` is either 'regex' or 'llm', and `reason` explains why that
// classifier was chosen (useful for debugging the hybrid routing).
export type IntentResult =
  | { type: 'immediate'; intent: string; name?: string; classifier: 'regex' | 'llm'; reason: string }
  | { type: 'clarification'; question: string; classifier: 'regex' | 'llm'; reason: string }
  | { type: 'conversation'; text: string; classifier: 'regex' | 'llm'; reason: string }
  | { type: 'motion'; description: string; classifier: 'regex' | 'llm'; reason: string }

export interface ChatMsg {
  role: 'agent' | 'child' | 'system'
  text: string
}

function msgsToHistory(msgs: ChatMsg[]): { role: 'user' | 'assistant'; content: string }[] {
  const out: { role: 'user' | 'assistant'; content: string }[] = []
  for (const m of msgs) {
    if (m.role === 'child') out.push({ role: 'user', content: m.text })
    else if (m.role === 'agent') out.push({ role: 'assistant', content: m.text })
    // 'system' messages (e.g. "Starting countdown…") are UI-only, skip them
  }
  return out
}

export async function classifyIntent(
  text: string,
  followActive: boolean,
  msgs?: ChatMsg[],
  sessionId?: string,
): Promise<IntentResult> {
  const history = msgs ? msgsToHistory(msgs) : undefined
  const res = await fetch('http://localhost:8000/classify-intent', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, follow_active: followActive, history, session_id: sessionId }),
  })
  // If the classifier cannot confidently propose a concrete movement, fall back to
  // conversation so the agent chats/asks instead of showing the approve/reject modal.
  if (!res.ok) return { type: 'conversation', text, classifier: 'llm', reason: 'classifier request failed' }
  const data = await res.json()
  if (data.type === 'immediate' && data.intent) return data as IntentResult
  if (data.type === 'clarification' && data.question) return data as IntentResult
  if (data.type === 'conversation' && data.text) return data as IntentResult
  if (data.type === 'motion' && data.description) return data as IntentResult
  return { type: 'conversation', text, classifier: 'llm', reason: 'unrecognized classifier response' }
}

export async function listPoses(): Promise<string[]> {
  const res = await fetch('http://localhost:8000/poses')
  if (!res.ok) return []
  const data = await res.json()
  return data.poses ?? []
}

export async function saveCurrentPose(name: string): Promise<void> {
  await fetch('http://localhost:8000/poses/save-current', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
}

// Strike a saved pose directly by name (no LLM). Used by the end-session replay.
export async function playPose(name: string, durationMs = 1000): Promise<void> {
  const res = await fetch('http://localhost:8000/poses/play', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, duration_ms: durationMs }),
  })
  if (!res.ok) throw new Error(`play pose failed: ${res.status}`)
}

// Short camera-shutter blip via WebAudio (no asset needed).
export function playShutter(): void {
  try {
    const ctx = new AudioContext()
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.type = 'square'
    osc.frequency.setValueAtTime(1200, ctx.currentTime)
    gain.gain.setValueAtTime(0.08, ctx.currentTime)
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.12)
    osc.connect(gain).connect(ctx.destination)
    osc.start()
    osc.stop(ctx.currentTime + 0.12)
    osc.onended = () => ctx.close().catch(() => {})
  } catch {
    /* audio is optional */
  }
}
