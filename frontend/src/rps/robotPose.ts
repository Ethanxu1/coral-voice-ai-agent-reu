import { resetPose, setPose } from '../api/robot'
import { ROBOT_REST_PULSES } from './gestures'
import { sleep } from '../utils/sleep'

const STEPS = 10


let current: Record<string, number> = { ...ROBOT_REST_PULSES }
let token = 0

/**
 * Move the simulator robot's arms to `target`, easing from wherever they are.
 *
 * /set-pose snaps joints instantly, and an instant full-arm swing can topple
 * the physics model even when the start and end poses are both stable. Sending
 * a series of small steps avoids that. A newer call cancels an older one that
 * is still easing.
 */
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

/** Snap the whole robot back to a clean stand. */
export async function resetRobot(): Promise<void> {
  token++
  current = { ...ROBOT_REST_PULSES }
  await resetPose()
}
