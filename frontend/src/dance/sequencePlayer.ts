// Runs a dance program (the steps under the start block) on the simulator robot,
// and on the physical robot too when `toRobot` (live mode's Execute).
//
// Pure async logic, no React: the page owns the cancellation token and React
// state, this just walks the steps.

import { resetPose, setPose } from '../api/robot'
import { SPEED_MS, danceMove } from './poses'
import type { Step } from './blocks'

type PoseStep = Extract<Step, { kind: 'pose' }>

/**
 * How long the last pose is held before the robot stands back up. Every other
 * pose shows while the next move glides out of it, but the closing reset drops
 * straight into stand, so without a hold the last pose is gone the moment it lands.
 */
const FINAL_HOLD_MS = 1000

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))

/**
 * Glide the sim to one pose. The request returns once the robot's body has
 * actually arrived there (or stopped short), so the next move starts from the
 * finished pose. An instant snap can topple the physics model, so every move is a glide.
 */
async function glideTo(pose: PoseStep['pose'], durationMs: number, toRobot: boolean): Promise<void> {
  const move = danceMove(pose)
  if (move) await setPose(move.robotPulses, { durationMs, waitUntilArrived: true, toRobot })
}

async function playSteps(
  steps: Step[],
  isAlive: () => boolean,
  toRobot: boolean,
  onStep?: (step: PoseStep) => void,
): Promise<void> {
  for (const step of steps) {
    if (!isAlive()) return
    if (step.kind === 'pose') {
      onStep?.(step)
      await glideTo(step.pose, SPEED_MS[step.speed], toRobot)
    } else {
      for (let i = 0; i < step.times; i++) {
        if (!isAlive()) return
        await playSteps(step.body, isAlive, toRobot, onStep)
      }
    }
  }
}

/**
 * Play the program once (repeat steps loop themselves), from a clean stand
 * and, after holding the last pose, back to one at the end (a reset, not a glide: gliding out of a deep
 * pose like Warrior can fold the sim over). `isAlive()` is checked before every
 * move so a cancellation (Stop, or the page unmounting) lands after the
 * current move has arrived instead of mid-glide. No stand between repeat laps: one pose
 * glides straight into the next, so the routine reads as continuous.
 * `toRobot` also moves the physical robot when the server is in live mode;
 * otherwise only the sim moves (its resets too).
 */
export async function playSequence(
  steps: Step[],
  isAlive: () => boolean,
  onStep?: (step: PoseStep) => void,
  { toRobot = false }: { toRobot?: boolean } = {},
): Promise<void> {
  const reset = () => resetPose({ simOnly: !toRobot })
  await reset()
  if (isAlive()) await playSteps(steps, isAlive, toRobot, onStep)
  if (isAlive()) await sleep(FINAL_HOLD_MS)
  if (isAlive()) await reset()
}
