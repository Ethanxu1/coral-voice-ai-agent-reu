// Runs a dance program (the steps under the start block) on the simulator robot.
//
// Pure async logic, no React: the page owns the cancellation token and React
// state, this just walks the steps.

import { resetPose, setPose } from '../api/robot'
import { DANCE_POSE_BY_ID, SPEED_MS } from './poses'
import type { Step } from './blocks'

type PoseStep = Extract<Step, { kind: 'pose' }>

/**
 * Glide the sim to one pose. The request returns once the robot's body has
 * actually arrived there (or stopped short), so the next move starts from the
 * finished pose. An instant snap can topple the physics model, so every move is a glide.
 */
const glideTo = (pose: PoseStep['pose'], durationMs: number) =>
  setPose(DANCE_POSE_BY_ID[pose].robotPulses, { durationMs, waitUntilArrived: true })

async function playSteps(steps: Step[], isAlive: () => boolean, onStep?: (step: PoseStep) => void): Promise<void> {
  for (const step of steps) {
    if (!isAlive()) return
    if (step.kind === 'pose') {
      onStep?.(step)
      await glideTo(step.pose, SPEED_MS[step.speed])
    } else {
      for (let i = 0; i < step.times; i++) {
        if (!isAlive()) return
        await playSteps(step.body, isAlive, onStep)
      }
    }
  }
}

/**
 * Play the program once (repeat steps loop themselves), from a clean stand
 * and back to one at the end (a reset, not a glide: gliding out of a deep
 * pose like Warrior can fold the sim over). `isAlive()` is checked before every
 * move so a cancellation (Stop, or the page unmounting) lands after the
 * current move has arrived instead of mid-glide. No stand between repeat laps: one pose
 * glides straight into the next, so the routine reads as continuous.
 */
export async function playSequence(
  steps: Step[],
  isAlive: () => boolean,
  onStep?: (step: PoseStep) => void,
): Promise<void> {
  await resetPose()
  if (isAlive()) await playSteps(steps, isAlive, onStep)
  if (isAlive()) await resetPose()
}
