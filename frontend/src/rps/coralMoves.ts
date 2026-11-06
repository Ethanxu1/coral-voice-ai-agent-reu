// CORAL's body language in the Play screen: a wave hello, and a reaction after
// each round. Arms and head only (hardware servo pulses, like gestures.ts), so
// nothing here can shift the robot's balance. Tuned by eye in the simulator.

import { ROBOT_REST_PULSES } from './gestures'
import { poseRobot } from './robotPose'

type Pulses = Record<string, number>

/** Left-arm values, mirrored onto the right arm (right = 1000 - left). */
function bothArms(left: { sho_pitch: number; sho_roll: number; el_pitch: number; el_yaw: number }, extra: Pulses = {}): Pulses {
  const out: Pulses = { ...extra }
  for (const [joint, v] of Object.entries(left)) {
    out[`l_${joint}`] = v
    out[`r_${joint}`] = 1000 - v
  }
  return out
}

const HEAD_LEVEL = { head_pan: 500, head_tilt: 500 }
const REST: Pulses = { ...ROBOT_REST_PULSES, ...HEAD_LEVEL }

/** Both arms up in a cheer, then a flex: CORAL won the round. */
const CHEER = bothArms({ sho_pitch: 185, sho_roll: 729, el_pitch: 625, el_yaw: 170 }, HEAD_LEVEL)
const FLEX = bothArms({ sho_pitch: 348, sho_roll: 601, el_pitch: 507, el_yaw: 26 }, HEAD_LEVEL)
/** Arms hanging forward, head down: the child won. */
const SLUMP = bothArms({ sho_pitch: 680, sho_roll: 880, el_pitch: 500, el_yaw: 150 }, { head_pan: 500, head_tilt: 360 })
/** Forearms out to the sides: a draw. */
const SHRUG = bothArms({ sho_pitch: 835, sho_roll: 760, el_pitch: 300, el_yaw: 0 }, HEAD_LEVEL)

/** Right arm raised, swinging between these two. */
const WAVE_OUT: Pulses = { r_sho_pitch: 837, r_sho_roll: 254, r_el_pitch: 413, r_el_yaw: 732 }
const WAVE_IN: Pulses = { r_sho_pitch: 837, r_sho_roll: 330, r_el_pitch: 413, r_el_yaw: 850 }

/** Each step of a sequence, in order; stops between steps once `cancelled` says so. */
async function sequence(steps: Pulses[], cancelled: () => boolean): Promise<void> {
  for (const step of steps) {
    if (cancelled()) return
    await poseRobot(step).catch((e) => console.warn('robot move failed', e))
  }
}

export const coralMoves = {
  wave: (cancelled: () => boolean) => sequence([WAVE_OUT, WAVE_IN, WAVE_OUT, WAVE_IN, REST], cancelled),
  /** CORAL's reaction to the round, from its side: it won, it lost, or a draw. */
  react: (outcome: 'coral' | 'child' | 'draw', cancelled: () => boolean) =>
    sequence(outcome === 'coral' ? [CHEER, FLEX] : outcome === 'child' ? [SLUMP] : [SHRUG], cancelled),
  /** The end-of-match dance, whoever won. */
  dance: (cancelled: () => boolean) => sequence([CHEER, FLEX, CHEER, FLEX, REST], cancelled),
}
