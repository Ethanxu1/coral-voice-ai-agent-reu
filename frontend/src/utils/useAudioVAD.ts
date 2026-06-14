import { useRef, useCallback } from 'react'

interface VADOptions {
  silenceMs?: number         // how long silence must last before triggering (default 1200ms)
  silenceThreshold?: number  // RMS energy threshold 0–255 (default 10)
  onSpeechStart?: () => void
  onSpeechEnd?: (blob: Blob) => void
}

interface VADHandle {
  start: () => Promise<void>
  pause: () => void
}

export function useAudioVAD(options: VADOptions): VADHandle {
  const {
    silenceMs = 1200,
    silenceThreshold = 10,
    onSpeechStart,
    onSpeechEnd,
  } = options

  const stateRef = useRef<{
    stream: MediaStream | null
    recorder: MediaRecorder | null
    analyser: AnalyserNode | null
    ctx: AudioContext | null
    chunks: Blob[]
    speaking: boolean
    silenceSince: number | null
    rafId: number | null
    active: boolean
  }>({
    stream: null, recorder: null, analyser: null, ctx: null,
    chunks: [], speaking: false, silenceSince: null, rafId: null, active: false,
  })

  const teardown = useCallback(() => {
    const s = stateRef.current
    s.active = false
    if (s.rafId != null) cancelAnimationFrame(s.rafId)
    s.rafId = null
    if (s.recorder && s.recorder.state !== 'inactive') s.recorder.stop()
    s.recorder = null
    s.stream?.getTracks().forEach(t => t.stop())
    s.stream = null
    s.ctx?.close()
    s.ctx = null
    s.analyser = null
    s.speaking = false
    s.silenceSince = null
    s.chunks = []
  }, [])

  const startSegment = useCallback(() => {
    const s = stateRef.current
    if (!s.stream) return
    s.chunks = []
    const recorder = new MediaRecorder(s.stream)
    recorder.ondataavailable = e => { if (e.data.size > 0) s.chunks.push(e.data) }
    recorder.onstop = () => {
      if (s.chunks.length > 0) {
        const blob = new Blob(s.chunks, { type: 'audio/webm' })
        onSpeechEnd?.(blob)
      }
      s.chunks = []
      // restart segment if still active
      if (s.active) startSegment()
    }
    recorder.start()
    s.recorder = recorder
  }, [onSpeechEnd])

  const tick = useCallback(() => {
    const s = stateRef.current
    if (!s.active || !s.analyser) return

    const buf = new Uint8Array(s.analyser.fftSize)
    s.analyser.getByteTimeDomainData(buf)
    // compute RMS energy (values are 0–255 centered at 128)
    let sum = 0
    for (let i = 0; i < buf.length; i++) { const v = buf[i] - 128; sum += v * v }
    const rms = Math.sqrt(sum / buf.length)

    const now = performance.now()
    if (rms > silenceThreshold) {
      if (!s.speaking) {
        s.speaking = true
        s.silenceSince = null
        onSpeechStart?.()
      } else {
        s.silenceSince = null
      }
    } else {
      if (s.speaking) {
        if (s.silenceSince == null) s.silenceSince = now
        else if (now - s.silenceSince > silenceMs) {
          s.speaking = false
          s.silenceSince = null
          // stop recorder — onstop will fire onSpeechEnd and restart
          if (s.recorder && s.recorder.state === 'recording') s.recorder.stop()
        }
      }
    }

    s.rafId = requestAnimationFrame(tick)
  }, [silenceThreshold, silenceMs, onSpeechStart])

  const start = useCallback(async () => {
    teardown()
    const s = stateRef.current
    s.active = true
    s.stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    const ctx = new AudioContext()
    const source = ctx.createMediaStreamSource(s.stream)
    const analyser = ctx.createAnalyser()
    analyser.fftSize = 512
    source.connect(analyser)
    s.ctx = ctx
    s.analyser = analyser
    startSegment()
    s.rafId = requestAnimationFrame(tick)
  }, [teardown, startSegment, tick])

  const pause = useCallback(() => {
    teardown()
  }, [teardown])

  return { start, pause }
}
