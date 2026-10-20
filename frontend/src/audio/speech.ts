// Audio output: OpenAI TTS through the backend, and UI sound effects.

import { SERVER_BASE } from '../config'

// ── Speech (OpenAI TTS via the backend's /speak) ─────────────────────────────
// One shared element so a new line (or killSpeech) cuts off the previous one.
let speechAudio: HTMLAudioElement | null = null

/** Speak `text` aloud; resolves when playback ends or is cut off. */
export async function speak({ text }: { text: string }): Promise<void> {
  const res = await fetch(`${SERVER_BASE}/speak`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })
  if (!res.ok) throw new Error(`speak failed: ${res.status}`)
  const url = URL.createObjectURL(await res.blob())
  await killSpeech()
  const audio = new Audio(url)
  speechAudio = audio
  try {
    await new Promise<void>((resolve, reject) => {
      audio.onended = () => resolve()
      audio.onpause = () => resolve()
      audio.onerror = () => reject(new Error('speech playback failed'))
      audio.play().catch(reject)
    })
  } finally {
    URL.revokeObjectURL(url)
    if (speechAudio === audio) speechAudio = null
  }
}

/** Stop any in-progress speech immediately (tab closed / demo restarted). */
export async function killSpeech(): Promise<void> {
  speechAudio?.pause()
  speechAudio = null
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
