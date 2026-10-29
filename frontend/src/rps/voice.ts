// CORAL's voice in Rock Paper Scissors: pre-generated ElevenLabs clips.
//
// The game only says a fixed set of lines (voiceLines.json), so they are made
// once by backend/tools/generate_rps_voice.py and served from
// public/rps/voice/<id>.mp3: instant, offline, the same on every OS. If a clip
// is missing (a line added without regenerating), the browser's own speech
// says the text instead.

import { killSpeech, speak } from '../audio/speech'
import LINES from './voiceLines.json'

export type LineId = keyof typeof LINES
export const VOICE_LINES: Record<LineId, string> = LINES

const clips = new Map<LineId, HTMLAudioElement>()
let current: HTMLAudioElement | null = null
let muted = false

function clip(id: LineId): HTMLAudioElement {
  let audio = clips.get(id)
  if (!audio) {
    audio = new Audio(`/rps/voice/${id}.mp3`)
    audio.preload = 'auto'
    clips.set(id, audio)
  }
  return audio
}

/** Start loading every clip, so the first time each line is said there is no delay. */
export function preloadVoice(): void {
  for (const id of Object.keys(LINES) as LineId[]) clip(id)
}

/** Stop whatever CORAL is saying. */
export function stopVoice(): void {
  current?.pause()
  current = null
  killSpeech()
}

/** Say one of CORAL's lines, cutting off any line still playing. */
export function sayLine(id: LineId): void {
  stopVoice()
  if (muted) return
  const audio = clip(id)
  current = audio
  audio.currentTime = 0
  audio.play().catch(() => {
    // No clip for this line (or it failed to load): fall back to the browser's voice.
    if (current === audio && audio.error) speak({ text: LINES[id] }).catch(() => {})
  })
}

/** Mute or unmute CORAL's voice; muting also cuts off the current line. */
export function setVoiceMuted(value: boolean): void {
  muted = value
  if (muted) stopVoice()
}
