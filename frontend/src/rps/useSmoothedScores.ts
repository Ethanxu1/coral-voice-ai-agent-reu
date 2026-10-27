import { useEffect, useRef, useState } from 'react'

/**
 * Averaging time: landmark jitter (frame to frame) averages out, while a real
 * arm movement, which takes a few hundred ms, still shows.
 */
const SMOOTH_MS = 450
/** The display changes this often: a child can follow a few updates a second, not the camera's 30. */
const SHOW_EVERY_MS = 250
/** Shown scores are rounded to this… */
const SHOW_STEP = 0.1
/**
 * …and a shown score only changes once the average is this far from it, so a
 * pose held at the edge of two steps (or of the match line) doesn't blink.
 */
const SHOW_DEADBAND = 0.07

/**
 * Similarity scores made readable for a child: averaged over time, updated a few
 * times a second and rounded to 10%. `matched` is the move whose card should be
 * green: the best move, if its shown score is at the line, so the colour always
 * agrees with the number. Display only: the game still judges from the raw scores.
 */
export function useSmoothedScores<K extends string>(
  scores: Record<K, number> | null,
  match: number,
): { shown: Record<K, number> | null; matched: K | null } {
  const avg = useRef<{ s: Record<K, number>; at: number } | null>(null)

  useEffect(() => {
    const now = performance.now()
    if (!scores) {
      avg.current = null
      return
    }
    const prev = avg.current
    if (!prev) {
      avg.current = { s: { ...scores }, at: now }
      return
    }
    const a = 1 - Math.exp(-(now - prev.at) / SMOOTH_MS)
    const s = { ...prev.s }
    for (const k of Object.keys(scores) as K[]) s[k] = (s[k] ?? scores[k]) + a * (scores[k] - (s[k] ?? scores[k]))
    avg.current = { s, at: now }
  }, [scores])

  const [view, setView] = useState<{ shown: Record<K, number> | null; matched: K | null }>({ shown: null, matched: null })

  useEffect(() => {
    const id = setInterval(() => {
      const s = avg.current?.s ?? null
      setView((v) => {
        if (!s) return v.shown ? { shown: null, matched: null } : v
        const keys = Object.keys(s) as K[]
        const shown = {} as Record<K, number>
        for (const k of keys) {
          const old = v.shown?.[k]
          shown[k] = old !== undefined && Math.abs(s[k] - old) < SHOW_DEADBAND ? old : Math.round(s[k] / SHOW_STEP) * SHOW_STEP
        }
        const top = keys.reduce((a, b) => (s[b] > s[a] ? b : a))
        // Rounding error: 0.6000000001 must count as at the line.
        const matched = shown[top] >= match - 1e-9 ? top : null
        const same = v.shown && v.matched === matched && keys.every((k) => v.shown![k] === shown[k])
        return same ? v : { shown, matched }
      })
    }, SHOW_EVERY_MS)
    return () => clearInterval(id)
  }, [match])

  return view
}
