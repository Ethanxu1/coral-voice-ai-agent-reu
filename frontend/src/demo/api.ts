// REST + audio helpers used by the demo state machine.
//
// Everything here is a plain async function (no React) so the pipeline runner in
// useDemoMachine can `await` each step in sequence — this is what keeps the
// 3-2-1 countdown locked to the speaker audio and the camera-click held until
// /classify returns.

import { ACTION_WS, SPEAKER_BASE } from './config'
import { getFeaturesBase, getRobotBase, getRobotConfig } from './robotConfig'
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

// Drive the robot/sim with raw servo commands (from mapFeatures). No-op safe if
// the command list is empty.
export async function move(commands: ServoCommand[]): Promise<void> {
  if (commands.length === 0) return
  const res = await fetch(`${getRobotBase()}/move`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(commands),
  })
  if (!res.ok) throw new Error(`move failed: ${res.status}`)
}

// Apply a raw {joint: hardware_pulse} pose to the sim (testing tool). Pulses are
// the same hardware units authored in motions.py; the server converts them to sim
// radians. Sim only — always hits the main Mac server, not the Pi.
export async function setPose(
  pulses: Record<string, number>,
): Promise<{ applied: string[]; skipped: string[] }> {
  const res = await fetch(`${getRobotBase()}/set-pose`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pulses }),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(`set-pose failed: ${res.status} ${body?.detail ?? ''}`.trim())
  }
  const data = await res.json()
  return { applied: data.applied ?? [], skipped: data.skipped ?? [] }
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
  sendText(text: string, timeoutMs?: number): Promise<ActionResult>
  close(): void
}

export function openActionSession(): ActionSession {
  const ws = new WebSocket(ACTION_WS)

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
    async sendText(text, timeoutMs = 30000) {
      // Server won't emit a 'transcription' frame for text; seed it locally so the
      // caller sees what they typed as the "transcript" for UI parity with audio.
      return send({ type: 'chat', content: text }, timeoutMs, text)
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

// Placeholder intent classifier — synchronous regex/keyword matcher wrapped
// in a Promise so call sites don't change. This is intentionally dumb: the
// final integration hasn't been decided yet, so keep it deterministic, cheap,
// and easy to rip out. `follow_active` is used to disambiguate a bare "stop"
// (follow_stop only when the robot is currently following).
export async function classifyIntent(text: string, followActive: boolean): Promise<string> {
  const t = text.toLowerCase()

  // exit — end the session
  if (/\b(exit|quit|good\s?bye|bye|leave|(i'?m|we'?re)\s+done|all\s+done|end\s+session)\b/.test(t)) {
    return 'exit'
  }

  // follow_stop — either explicit ("stop following") or bare "stop" while following
  if (/\bstop\s+(following|mirroring|copying|imitating|tracking)\b/.test(t)) return 'follow_stop'
  if (followActive && /\bstop\b/.test(t)) return 'follow_stop'

  // follow_start — mirror/copy/imitate my movement
  if (/\b(follow|mirror|copy|imitate|track)\b/.test(t)) return 'follow_start'

  // capture — snapshot / freeze the current pose
  if (/\b(capture|snap|freeze|take\s+(?:a\s+)?(?:picture|photo|snapshot)|save\s+(?:my|this|the)\s+pose)\b/.test(t)) {
    return 'capture'
  }

  // library — see saved poses
  if (/\b(my\s+poses|library|saved\s+poses|show\s+(?:me\s+)?(?:my\s+)?poses|what\s+poses|see\s+(?:my\s+)?poses)\b/.test(t)) {
    return 'library'
  }

  return 'chat'
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
