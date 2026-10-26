// /ws conversation sessions with the main backend: chat, audio, transcription.

import { ACTION_WS } from '../config'
import { parseSafety, type MoveSafety } from './robot'

export interface ActionResult {
  transcript: string
  content: string
  hasAction: boolean
  satisfied?: boolean | null
  /** Safety verdict for the motion this turn executed; null when nothing moved. */
  safety?: MoveSafety | null
}

// ── Audio → transcript only (no LLM) over /ws ───────────────────────────────
// `transcribe_only` stops the server after Whisper. Without it the /ws audio
// handler runs the full intent + motion pipeline on this utterance and moves
// the robot — on top of the move the caller makes itself (e.g. the refined
// demo's map-features capture), so one "capture my pose" drove the robot twice.
export function sendAudioForTranscript(blob: Blob, timeoutMs = 30000): Promise<string> {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(ACTION_WS)
    const timer = setTimeout(() => { ws.close(); reject(new Error('transcription timed out')) }, timeoutMs)

    ws.onopen = async () => {
      const data = await blobToBase64(blob)
      ws.send(JSON.stringify({ type: 'audio', data, format: 'webm', transcribe_only: true }))
    }
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      if (data.type === 'transcription') {
        clearTimeout(timer)
        ws.close()
        resolve(data.text ?? '')
      }
    }
    ws.onerror = () => { clearTimeout(timer); reject(new Error('transcription ws error')) }
  })
}

// ── Persistent action session (multi-turn refinement) ────────────────────────
// One /ws socket kept open across a whole conversation, so the server's
// HierarchicalMemory (and the Langfuse trace) span every turn.
export interface ActionSession {
  sendAudio(
    blob: Blob,
    timeoutMs?: number,
    onAudio?: (audioUrl: string) => void,
  ): Promise<ActionResult>
  sendText(
    text: string,
    intentType?: 'motion' | 'conversation' | 'immediate' | 'clarification',
    description?: string,
    timeoutMs?: number,
    onAudio?: (audioUrl: string) => void,
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
    onAudio?: (audioUrl: string) => void
  }
  let pending: Pending | null = null
  let closed = false
  // Object URLs for assistant TTS audio; revoked when the session closes.
  const audioUrls: string[] = []

  const failPending = (err: Error) => {
    if (pending) {
      clearTimeout(pending.timer)
      pending.reject(err)
      pending = null
    }
  }

  ws.addEventListener('message', (event) => {
    const data = JSON.parse(event.data)
    if (data.type === 'audio_response' && data.audio_base64) {
      try {
        const bytes = Uint8Array.from(atob(data.audio_base64), (c) => c.charCodeAt(0))
        const blob = new Blob([bytes], { type: `audio/${data.format ?? 'mpeg'}` })
        const url = URL.createObjectURL(blob)
        audioUrls.push(url)
        pending?.onAudio?.(url)
      } catch {
        /* malformed audio frame — ignore */
      }
      return
    }
    if (!pending) return
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
        safety: parseSafety(data.safety),
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

  const send = async (
    payload: object,
    timeoutMs: number,
    initialTranscript = '',
    onAudio?: (audioUrl: string) => void,
  ): Promise<ActionResult> => {
    if (closed) throw new Error('action session already closed')
    if (pending) throw new Error('action session busy')
    await openPromise
    if (closed) throw new Error('action session already closed')
    return new Promise<ActionResult>((resolve, reject) => {
      const timer = setTimeout(() => {
        pending = null
        reject(new Error('action session timed out'))
      }, timeoutMs)
      pending = { transcript: initialTranscript, resolve, reject, timer, onAudio }
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
    async sendAudio(blob, timeoutMs = 30000, onAudio) {
      const base64 = await blobToBase64(blob)
      return send({ type: 'audio', data: base64, format: 'webm' }, timeoutMs, '', onAudio)
    },
    async sendText(text, intentType, description, timeoutMs = 30000, onAudio) {
      // Server won't emit a 'transcription' frame for text; seed it locally so the
      // caller sees what they typed as the "transcript" for UI parity with audio.
      const payload: Record<string, unknown> = { type: 'chat', content: text }
      if (intentType) payload.intent_type = intentType
      if (description) payload.description = description
      return send(payload, timeoutMs, text, onAudio)
    },
    close() {
      closed = true
      failPending(new Error('action session closed'))
      audioUrls.forEach((url) => {
        try { URL.revokeObjectURL(url) } catch { /* ignore */ }
      })
      audioUrls.length = 0
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
