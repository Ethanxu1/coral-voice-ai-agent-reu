// The Play screen's sound effects, synthesized with WebAudio (no asset files).
// A child standing back hears these instead of reading: a pop when CORAL sees a
// move, a chime when the move is locked in, and a tune for win, lose or tie.

type Note = { freq: number; at: number; len: number; type?: OscillatorType; gain?: number; slideTo?: number }

let ctx: AudioContext | null = null

function audio(): AudioContext | null {
  try {
    ctx ??= new AudioContext()
    if (ctx.state === 'suspended') ctx.resume().catch(() => {})
    return ctx
  } catch {
    return null
  }
}

function play(notes: Note[]) {
  const a = audio()
  if (!a) return
  const t0 = a.currentTime + 0.01
  for (const n of notes) {
    const osc = a.createOscillator()
    const gain = a.createGain()
    osc.type = n.type ?? 'triangle'
    osc.frequency.setValueAtTime(n.freq, t0 + n.at)
    if (n.slideTo) osc.frequency.exponentialRampToValueAtTime(n.slideTo, t0 + n.at + n.len)
    gain.gain.setValueAtTime(0.0001, t0 + n.at)
    gain.gain.exponentialRampToValueAtTime(n.gain ?? 0.18, t0 + n.at + 0.015)
    gain.gain.exponentialRampToValueAtTime(0.0001, t0 + n.at + n.len)
    osc.connect(gain).connect(a.destination)
    osc.start(t0 + n.at)
    osc.stop(t0 + n.at + n.len + 0.02)
  }
}

// Notes (Hz).
const C5 = 523, E5 = 659, G5 = 784, A5 = 880, C6 = 1047, E4 = 330, G4 = 392, C4 = 262

export const sfx = {
  /** The camera recognised a move. */
  seen: () => play([{ freq: G5, at: 0, len: 0.09, gain: 0.12, slideTo: C6 }]),
  /** The child is in place (upper body in view). */
  fit: () => play([{ freq: E5, at: 0, len: 0.16 }, { freq: A5, at: 0.1, len: 0.3 }]),
  /** One countdown word. */
  tick: () => play([{ freq: G4, at: 0, len: 0.14, type: 'square', gain: 0.08 }]),
  /** SHOOT. */
  shoot: () => play([{ freq: C5, at: 0, len: 0.35, type: 'sawtooth', gain: 0.1, slideTo: C6 }]),
  /** The child's move is locked in. */
  lock: () => play([{ freq: C6, at: 0, len: 0.12 }, { freq: G5, at: 0.08, len: 0.25 }]),
  /** No move was seen. */
  miss: () => play([{ freq: G4, at: 0, len: 0.25, slideTo: E4 }]),
  win: () => play([C5, E5, G5, C6].map((freq, i) => ({ freq, at: i * 0.11, len: i === 3 ? 0.45 : 0.14 }))),
  lose: () => play([{ freq: G4, at: 0, len: 0.22 }, { freq: E4, at: 0.2, len: 0.22 }, { freq: C4, at: 0.4, len: 0.5, slideTo: 220 }]),
  tie: () => play([{ freq: E5, at: 0, len: 0.16 }, { freq: E5, at: 0.2, len: 0.3 }]),
}
