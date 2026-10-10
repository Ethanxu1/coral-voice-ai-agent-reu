// Runs a programmed dance block-tree on the simulator robot.
//
// Pure async logic, no React — the page owns the cancellation token and React
// state, this just walks the blocks and calls into pose/robotPose.ts.

import { poseRobot, resetToStand } from '../pose/robotPose'
import { DANCE_POSE_BY_ID, SPEED_MS, STAND_PULSES } from './poses'
import type { Block } from './blocks'

async function playBlocks(blocks: Block[], isAlive: () => boolean, onStep?: (uid: string) => void): Promise<void> {
  for (const block of blocks) {
    if (!isAlive()) return
    if (block.type === 'pose') {
      onStep?.(block.uid)
      await poseRobot(DANCE_POSE_BY_ID[block.poseId].robotPulses, SPEED_MS[block.speed])
    } else {
      for (let i = 0; i < block.count; i++) {
        if (!isAlive()) return
        await playBlocks(block.children, isAlive, onStep)
      }
    }
    if (!isAlive()) return
  }
}

/**
 * Play the whole top-level block list once (repeat blocks within it loop
 * themselves). `isAlive()` is checked before and after every move so a
 * cancellation (Stop, or the page unmounting) lands cleanly instead of
 * mid-ease. No reset-to-stand between repeat-block laps — one pose eases
 * straight into the next, so the routine reads as continuous rather than
 * stuttering to attention every lap.
 */
export async function playSequence(
  blocks: Block[],
  isAlive: () => boolean,
  onStep?: (uid: string) => void,
): Promise<void> {
  await resetToStand(STAND_PULSES)
  if (isAlive()) await playBlocks(blocks, isAlive, onStep)
  if (isAlive()) await resetToStand(STAND_PULSES)
}
