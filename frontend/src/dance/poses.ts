// Dance Game moves and speeds.
//
// Every move on the Dance Game shelf is a pose the child made in the Pose
// Designer (poseDesigner/customPoses.ts); there are no preset moves (removed
// 2026-11-12). STAND_PULSES is the robot's resting stand, the base every
// designed pose is built on (poseDesigner/capture.ts).

import { loadCustomPoses } from '../poseDesigner/customPoses'

/** The resting stand: hardware servo pulses (0-1000), full body. From backend/app/robot/motions.py STAND_PULSE. */
export const STAND_PULSES: Record<string, number> = {
  l_ank_roll: 500, r_ank_roll: 500,
  l_ank_pitch: 640, r_ank_pitch: 360,
  l_knee: 500, r_knee: 500,
  l_hip_pitch: 350, r_hip_pitch: 650,
  l_hip_roll: 500, r_hip_roll: 500,
  l_hip_yaw: 500, r_hip_yaw: 500,
  l_sho_pitch: 835, r_sho_pitch: 165,
  l_sho_roll: 830, r_sho_roll: 170,
  l_el_pitch: 500, r_el_pitch: 500,
  l_el_yaw: 150, r_el_yaw: 850,
  l_gripper: 500, r_gripper: 500,
  head_pan: 500, head_tilt: 500,
}

export type DanceSpeed = 'slow' | 'normal' | 'fast'

/** How long each move takes to glide into, per speed choice. */
export const SPEED_MS: Record<DanceSpeed, number> = {
  slow: 1400,
  normal: 700,
  fast: 350,
}

/** The speed dropdown's text on each move block, in dropdown order. */
export const SPEED_LABEL: Record<DanceSpeed, string> = {
  slow: '🐢 slow',
  normal: '🚶 normal',
  fast: '🐇 fast',
}

/** A move a block can play: a pose the child made in the Pose Designer. */
export interface DanceMove {
  label: string
  emoji: string
  /** Hardware servo pulses (0-1000, 500 = centre), full body. */
  robotPulses: Record<string, number>
}

/** The emoji on a move's block (and its icon if the stick figure can't be drawn). */
export const CUSTOM_EMOJI = '⭐'

/** The move with this CustomPose id, or undefined if it no longer exists. */
export function danceMove(id: string): DanceMove | undefined {
  const custom = loadCustomPoses().find((p) => p.id === id)
  return custom && { label: custom.name, emoji: CUSTOM_EMOJI, robotPulses: custom.pulses }
}
