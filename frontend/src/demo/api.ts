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
// Compact VAD: record until ~1.2s of silence after speech, or maxMs elapsed.
export async function captureUtterance(
  opts: { silenceMs?: number; maxMs?: number; threshold?: number; onLevel?: (rms: number) => void } = {},
): Promise<Blob> {
  const { silenceMs = 1200, maxMs = 12000, threshold = 10, onLevel } = opts
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
  const ctx = new AudioContext()
  const source = ctx.createMediaStreamSource(stream)
  const analyser = ctx.createAnalyser()
  analyser.fftSize = 512
  source.connect(analyser)

  const recorder = new MediaRecorder(stream)
  const chunks: Blob[] = []
  recorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data) }
  recorder.start()

  const buf = new Uint8Array(analyser.fftSize)
  let speaking = false
  let silenceSince: number | null = null
  const startedAt = performance.now()

  const cleanup = () => {
    stream.getTracks().forEach((t) => t.stop())
    ctx.close().catch(() => {})
  }

  return new Promise<Blob>((resolve) => {
    recorder.onstop = () => {
      cleanup()
      resolve(new Blob(chunks, { type: 'audio/webm' }))
    }
    const tick = () => {
      if (recorder.state !== 'recording') return
      analyser.getByteTimeDomainData(buf)
      let sum = 0
      for (let i = 0; i < buf.length; i++) { const v = buf[i] - 128; sum += v * v }
      const rms = Math.sqrt(sum / buf.length)
      onLevel?.(rms)
      const now = performance.now()
      if (rms > threshold) {
        speaking = true
        silenceSince = null
      } else if (speaking) {
        if (silenceSince == null) silenceSince = now
        else if (now - silenceSince > silenceMs) { recorder.stop(); return }
      }
      if (now - startedAt > maxMs) { recorder.stop(); return }
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
export function sendAudioForAction(blob: Blob, timeoutMs = 30000): Promise<ActionResult> {
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
      } else if (data.type === 'chat_response') {
        clearTimeout(timer)
        ws.close()
        const waypoints = Array.isArray(data.waypoints) ? data.waypoints : []
        resolve({ transcript, content: data.content ?? '', hasAction: waypoints.length > 0 })
      }
    }
    ws.onerror = () => { clearTimeout(timer); reject(new Error('audio-to-action ws error')) }
  })
}

// ── Text → action over the existing server.py /ws pipeline ────────────────────
// Text-input equivalent of sendAudioForAction: sends a typed instruction straight
// to the LLM motion planner (skipping Whisper) and waits for the chat_response.
export function sendTextForAction(text: string, timeoutMs = 30000): Promise<ActionResult> {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(ACTION_WS)
    const timer = setTimeout(() => { ws.close(); reject(new Error('text-to-action timed out')) }, timeoutMs)

    ws.onopen = () => {
      ws.send(JSON.stringify({ type: 'chat', content: text }))
    }
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      if (data.type === 'chat_response') {
        clearTimeout(timer)
        ws.close()
        const waypoints = Array.isArray(data.waypoints) ? data.waypoints : []
        resolve({ transcript: text, content: data.content ?? '', hasAction: waypoints.length > 0 })
      }
    }
    ws.onerror = () => { clearTimeout(timer); reject(new Error('text-to-action ws error')) }
  })
}

// ── Misc ──────────────────────────────────────────────────────────────────────
export function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
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
