// The 8 arm servos a gesture sets, described for people fine-tuning them.
//
// Pulses are hardware servo units (0-1000, 500 = servo centre, 1000 units =
// 240 degrees), the same format as robot/motions.py. Note the YAML names
// el_pitch / el_yaw are swapped relative to what the joints physically do (see
// backend/app/robot/servo_config.py): el_yaw bends the elbow, el_pitch twists
// the forearm.
//
// The two arms are mirror images: the same move on the other arm is 1000 - pulse
// (e.g. the stand pose is l_sho_pitch 835 / r_sho_pitch 165).

export type ArmSide = 'l' | 'r'

export interface ArmJointDef {
  /** Joint name without the l_/r_ prefix. */
  key: string
  label: string
  hint: string
}

/** In the order shown in the fine-tune panel, shoulder to hand. */
export const ARM_JOINT_DEFS: ArmJointDef[] = [
  { key: 'sho_pitch', label: 'Shoulder swing', hint: 'Swings the whole arm forward, up and back.' },
  { key: 'sho_roll', label: 'Shoulder raise', hint: 'Lifts the arm out to the side, away from the body.' },
  { key: 'el_yaw', label: 'Elbow bend', hint: 'Bends the elbow.' },
  { key: 'el_pitch', label: 'Forearm twist', hint: 'Twists the forearm around its own axis.' },
]

export const jointId = (side: ArmSide, key: string) => `${side}_${key}`

export const ARM_JOINT_IDS: string[] = (['l', 'r'] as const).flatMap((side) =>
  ARM_JOINT_DEFS.map((d) => jointId(side, d.key)),
)

/** The matching joint on the other arm. */
export function mirrorJoint(joint: string): string {
  return joint.startsWith('l_') ? `r_${joint.slice(2)}` : `l_${joint.slice(2)}`
}

export const mirrorPulse = (pulse: number) => 1000 - pulse

export const PULSE_MIN = 0
export const PULSE_MAX = 1000
const DEGREES_PER_PULSE = 240 / 1000

/** Servo angle from centre, e.g. "+42°". */
export function pulseToDegreesLabel(pulse: number): string {
  const deg = Math.round((pulse - 500) * DEGREES_PER_PULSE)
  return `${deg > 0 ? '+' : ''}${deg}°`
}

/** Just the arm joints of a full {joint: pulse} pose. */
export function armPulses(all: Record<string, number>): Record<string, number> {
  return Object.fromEntries(ARM_JOINT_IDS.filter((j) => j in all).map((j) => [j, Math.round(all[j])]))
}
