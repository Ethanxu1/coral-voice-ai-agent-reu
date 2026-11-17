// Audio output: CORAL's voice (the browser's own speech synthesis) and UI sound effects.

// ── Speech (the browser's Web Speech API) ────────────────────────────────────
// Spoken by the browser with a system voice: instant and offline. The OpenAI TTS
// route (/speak) took 1-3 s per line and sometimes stalled for 10 s or more, so
// lines came late or not at all mid-game. On a Mac this is the same Samantha
// voice the first version of the game used through `say`.

/** Preferred voices, by name; otherwise any local US English voice. */
const VOICE_NAMES = ['Samantha']
/** 1 is the voice's normal pace, about `say -r 180` for Samantha: calm, not rushed. */
const RATE = 1
/**
 * Chrome sometimes never fires onend/onerror (an utterance queued right after
 * cancel(), or a Linux speech backend that wedges), which would leave a caller
 * awaiting speak() forever. Give up after a generous estimate of the line's length.
 */
const MAX_MS_PER_CHAR = 120
const MAX_SPEECH_EXTRA_MS = 3000

let voice: SpeechSynthesisVoice | null = null
// Kept so Chrome doesn't garbage-collect a playing utterance and skip its onend.
let current: SpeechSynthesisUtterance | null = null
// Settles the pending speak() at once: killSpeech() can't rely on cancel()
// firing onerror for an utterance the browser has wedged.
let finishCurrent: (() => void) | null = null

function pickVoice(): SpeechSynthesisVoice | null {
  const voices = speechSynthesis.getVoices()
  return (
    voices.find((v) => VOICE_NAMES.includes(v.name)) ??
    voices.find((v) => v.lang === 'en-US' && v.localService) ??
    null
  )
}

const supported = typeof window !== 'undefined' && 'speechSynthesis' in window
if (supported) {
  // Chrome fills the voice list asynchronously.
  voice = pickVoice()
  speechSynthesis.addEventListener('voiceschanged', () => (voice = pickVoice()))
}

/** Speak `text` aloud, cutting off any line still playing; resolves when it ends or is cut off (or, if the browser never says, after it should have ended). */
export async function speak({ text }: { text: string }): Promise<void> {
  if (!supported) return
  finishCurrent?.()
  speechSynthesis.cancel()
  const u = new SpeechSynthesisUtterance(text)
  if (voice) u.voice = voice
  u.lang = voice?.lang ?? 'en-US'
  u.rate = RATE
  current = u
  let timer: ReturnType<typeof setTimeout> | undefined
  try {
    await new Promise<void>((resolve) => {
      finishCurrent = resolve
      u.onend = () => resolve()
      u.onerror = () => resolve()
      timer = setTimeout(resolve, text.length * MAX_MS_PER_CHAR + MAX_SPEECH_EXTRA_MS)
      speechSynthesis.speak(u)
    })
  } finally {
    clearTimeout(timer)
    if (current === u) {
      current = null
      finishCurrent = null
    }
  }
}

/** Stop any in-progress speech immediately (tab closed / demo restarted). */
export async function killSpeech(): Promise<void> {
  if (supported) speechSynthesis.cancel()
  finishCurrent?.()
  finishCurrent = null
  current = null
}

// Soft two-note chime via WebAudio: "I heard you, go ahead" (wake word).
export function playChime(): void {
  try {
    const ctx = new AudioContext()
    const gain = ctx.createGain()
    gain.gain.setValueAtTime(0.0001, ctx.currentTime)
    gain.gain.exponentialRampToValueAtTime(0.06, ctx.currentTime + 0.02)
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.35)
    gain.connect(ctx.destination)
    const osc = ctx.createOscillator()
    osc.type = 'sine'
    osc.frequency.setValueAtTime(660, ctx.currentTime)
    osc.frequency.setValueAtTime(880, ctx.currentTime + 0.12)
    osc.connect(gain)
    osc.start()
    osc.stop(ctx.currentTime + 0.35)
    osc.onended = () => ctx.close().catch(() => {})
  } catch {
    /* audio is optional */
  }
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
