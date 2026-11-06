import { useEffect, useRef, useState } from 'react'
import { normalizePose, poseSimilarity, type MatchOptions, type PoseVector } from '../pose/poseSimilarity'
import type { Landmark } from '../types/pose'

/** Hold the pose this long to confirm it. */
export const HOLD_MS = 1500
/**
 * Each frame must be at least this similar (0-1) to the pose held so far, using
 * the same similarity score as the Rock-Paper-Scissors matcher (maxDistance
 * below). 0.75 allows the arms to wander about 0.3 shoulder widths on average,
 * so natural sway and tracker jitter don't restart the hold.
 */
export const HOLD_SIMILARITY = 0.75
const HOLD_MAX_DISTANCE = 1.2
/** A brief wobble, or the tracker losing the arms, shorter than this is ignored. */
const GLITCH_MS = 400
/** With `canFinish`, confirm anyway once the pose has been held this long. */
export const MAX_HOLD_MS = 5000

export function meanPose(frames: PoseVector[]): PoseVector {
  const out: PoseVector = {}
  for (const name of Object.keys(frames[0]) as (keyof PoseVector)[]) {
    let x = 0
    let y = 0
    for (const f of frames) {
      x += f[name]![0]
      y += f[name]![1]
    }
    out[name] = [x / frames.length, y / frames.length]
  }
  return out
}

/**
 * While `active`, watches the live pose and calls `onHeld` with the averaged
 * pose once the person has kept roughly the same pose for HOLD_MS. Small
 * movements are fine; only changing to a clearly different pose (for longer than
 * GLITCH_MS) restarts the hold. Losing sight of the arms for longer than
 * GLITCH_MS restarts it too.
 *
 * `canFinish`, if given, must also return true before the hold is confirmed
 * (e.g. the robot has caught up); until then `waiting` is true. After
 * MAX_HOLD_MS the hold is confirmed regardless.
 *
 * Returns the hold progress (0-1) and `current()`, the pose held so far (or the
 * live pose if there isn't one yet), for a manual "save now".
 */
export function useHoldStill(
  body: Landmark[],
  active: boolean,
  onHeld: (pose: PoseVector) => void,
  opts: MatchOptions = {},
  canFinish?: () => boolean,
): { progress: number; waiting: boolean; current: () => PoseVector | null } {
  const [progress, setProgress] = useState(0)
  const [waiting, setWaiting] = useState(false)
  const canFinishRef = useRef(canFinish)
  canFinishRef.current = canFinish
  const framesRef = useRef<PoseVector[]>([])
  const startRef = useRef(0)
  // When the pose first went missing or off, if it still is.
  const offSinceRef = useRef<number | null>(null)
  const onHeldRef = useRef(onHeld)
  onHeldRef.current = onHeld
  const optsRef = useRef(opts)
  optsRef.current = opts

  const restart = (first: PoseVector | null) => {
    framesRef.current = first ? [first] : []
    startRef.current = Date.now()
    offSinceRef.current = null
    setProgress(0)
    setWaiting(false)
  }

  useEffect(() => {
    if (!active) {
      restart(null)
      return
    }
    const now = Date.now()
    const pose = normalizePose(body, optsRef.current)
    const frames = framesRef.current

    if (frames.length === 0) {
      if (pose) restart(pose)
      return
    }

    const similar =
      !!pose &&
      poseSimilarity(pose, meanPose(frames), { maxDistance: HOLD_MAX_DISTANCE, joints: optsRef.current.joints }) >=
        HOLD_SIMILARITY
    if (!similar) {
      // Ignore a short glitch; restart only if it lasts.
      offSinceRef.current ??= now
      if (now - offSinceRef.current > GLITCH_MS) restart(pose)
      return
    }

    offSinceRef.current = null
    frames.push(pose!)
    const held = now - startRef.current
    setProgress(Math.min(1, held / HOLD_MS))
    if (held >= HOLD_MS) {
      const ready = !canFinishRef.current || canFinishRef.current() || held >= MAX_HOLD_MS
      setWaiting(!ready)
      if (!ready) return
      const done = meanPose(frames)
      restart(null)
      setProgress(1)
      onHeldRef.current(done)
    }
  }, [body, active])

  const current = () =>
    framesRef.current.length > 0 ? meanPose(framesRef.current) : normalizePose(body, optsRef.current)

  return { progress, waiting, current }
}
