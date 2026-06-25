// REST + audio helpers used by the demo state machine.
//
// Everything here is a plain async function (no React) so the pipeline runner in
// useDemoMachine can `await` each step in sequence — this is what keeps the
// 3-2-1 countdown locked to the speaker audio and the camera-click held until
// /classify returns.

import { ACTION_WS, ROBOT_BASE, SPEAKER_BASE } from './config'

export interface ClassifyResult {
  className: string
  probabilities: Record<string, number>
  imageB64: string | null
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
  const res = await fetch(`${ROBOT_BASE}/motion`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, global_duration: globalDuration ?? null }),
  })
  if (!res.ok) throw new Error(`motion failed: ${res.status}`)
}

export async function classify(): Promise<ClassifyResult> {
  const res = await fetch(`${ROBOT_BASE}/classify`, { method: 'POST' })
  if (!res.ok) throw new Error(`classify failed: ${res.status}`)
  const data = await res.json()
  return {
    className: data.class,
    probabilities: data.probabilities ?? {},
    imageB64: data.image_b64 ?? null,
  }
}

export async function watchForAction(timeoutS: number): Promise<{ detected: boolean }> {
  const res = await fetch(`${ROBOT_BASE}/watch-for-action?timeout=${timeoutS}`)
  if (!res.ok) throw new Error(`watch-for-action failed: ${res.status}`)
  const data = await res.json()
  return { detected: !!data.detected }
}

export async function setRobotState(mode: string): Promise<void> {
  // Best-effort lock/unlock — never let a state toggle abort the demo.
  try {
    await fetch(`${ROBOT_BASE}/state`, {
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
