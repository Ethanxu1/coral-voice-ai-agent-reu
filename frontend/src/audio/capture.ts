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
