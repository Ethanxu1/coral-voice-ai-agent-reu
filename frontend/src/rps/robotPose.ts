import { resetPose, setPose } from '../demo/api'
import { ROBOT_REST_PULSES } from './gestures'

/**
 * Arm speed, the same as gentle follow mode (_GENTLE_MAX_STEP_RAD in
 * backend/app/follow_controller.py): 0.08 rad every 50 ms, about 1.6 rad/s or
 * 380 servo pulses per second. Faster swings can topple the simulated robot.
 */
const GENTLE_PULSES_PER_S = 380

let current: Record<string, number> = { ...ROBOT_REST_PULSES }

/**
 * Move the simulator robot's arms to `target` from wherever they are, at gentle
 * follow speed, and resolve when the move has finished.
 *
 * The move is one timed servo command that the simulator interpolates smoothly,
 * the same way follow mode drives the robot (an instant /set-pose snap can
 * topple the physics model). It takes at least `minDurationMs`.
 */
export async function poseRobot(target: Record<string, number>, minDurationMs = 400): Promise<void> {
  const biggest = Math.max(0, ...Object.keys(target).map((j) => Math.abs(target[j] - (current[j] ?? target[j]))))
  const durationMs = Math.max(minDurationMs, Math.round((biggest / GENTLE_PULSES_PER_S) * 1000))
  current = { ...current, ...target }
  await setPose(target, false, durationMs)
}

/** Snap the whole robot back to a clean stand. */
export async function resetRobot(): Promise<void> {
  current = { ...ROBOT_REST_PULSES }
  await resetPose()
}
