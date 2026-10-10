// Generic pose easing for the simulator robot, shared across games.
//
// /set-pose snaps joints instantly, and an instant full-body swing can topple
// the physics model even when the start and end poses are both stable. Sending
// a series of small steps avoids that. A newer call cancels an older one that
// is still easing.
//
// This is a sibling of rps/robotPose.ts (arms-only, RPS's own rest pose) kept
// separate rather than shared, so games can each own their idea of "rest."

import { resetPose, setPose } from '../demo/api'

const STEPS = 10

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))

let current: Record<string, number> = {}
let token = 0

/** Move the simulator robot to `target`, easing from wherever it currently is. */
export async function poseRobot(target: Record<string, number>, durationMs = 700): Promise<void> {
  const mine = ++token
  const from = current
  for (let i = 1; i <= STEPS; i++) {
    const t = i / STEPS
    const step: Record<string, number> = {}
    for (const joint of Object.keys(target)) {
      const a = from[joint] ?? target[joint]
      step[joint] = Math.round(a + (target[joint] - a) * t)
    }
    if (mine !== token) return
    await setPose(step)
    current = { ...current, ...step }
    await sleep(durationMs / STEPS)
  }
}

/**
 * Snap the whole robot to `standPulses` and reset this module's local
 * tracking to match, so the next `poseRobot()` call eases every joint in
 * `standPulses` instead of snapping any that have never been set before.
 */
export async function resetToStand(standPulses: Record<string, number>): Promise<void> {
  token++
  current = { ...standPulses }
  await resetPose()
}
