import { useEffect, useRef, useState } from 'react'

/**
 * Averaging time: landmark jitter (frame to frame) averages out, while an arm
 * movement still shows within a fraction of a second.
 */
const SMOOTH_MS = 200
/** The display changes this often, so the rings rise and fall smoothly. */
const SHOW_EVERY_MS = 50
/** Shown scores are rounded to this (whole percent). */
const SHOW_STEP = 0.01
/**
 * Once a move is matched it stays matched until its score drops this far below
 * the line, so a pose held right at the line doesn't make the card blink.
 */
const MATCH_HYSTERESIS = 0.04

/**
 * Similarity scores for display: averaged over time, updated 20 times a second
 * and rounded to whole percent. `matched` is the move whose card should be
 * green: the best move, once its shown score reaches the line. Display only:
 * the game still judges from the raw scores.
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
        for (const k of keys) shown[k] = Math.round(s[k] / SHOW_STEP) * SHOW_STEP
        const top = keys.reduce((a, b) => (s[b] > s[a] ? b : a))
        const line = v.matched === top ? match - MATCH_HYSTERESIS : match
        // Rounding error: 0.6000000001 must count as at the line.
        const matched = shown[top] >= line - 1e-9 ? top : null
        const same = v.shown && v.matched === matched && keys.every((k) => v.shown![k] === shown[k])
        return same ? v : { shown, matched }
      })
    }, SHOW_EVERY_MS)
    return () => clearInterval(id)
  }, [match])

  return view
}
