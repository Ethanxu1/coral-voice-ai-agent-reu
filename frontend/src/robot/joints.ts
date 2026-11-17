// The robot's 24 servo joints, grouped by body part, with display labels and
// the stand pose in hardware pulse units (0–1000, the motions.py format).

export const JOINT_GROUPS: { title: string; joints: string[] }[] = [
  { title: 'Head', joints: ['head_pan', 'head_tilt'] },
  { title: 'Left Arm', joints: ['l_sho_pitch', 'l_sho_roll', 'l_el_pitch', 'l_el_yaw', 'l_gripper'] },
  { title: 'Right Arm', joints: ['r_sho_pitch', 'r_sho_roll', 'r_el_pitch', 'r_el_yaw', 'r_gripper'] },
  { title: 'Left Leg', joints: ['l_hip_yaw', 'l_hip_roll', 'l_hip_pitch', 'l_knee', 'l_ank_pitch', 'l_ank_roll'] },
  { title: 'Right Leg', joints: ['r_hip_yaw', 'r_hip_roll', 'r_hip_pitch', 'r_knee', 'r_ank_pitch', 'r_ank_roll'] },
]

const PART_LABELS: Record<string, string> = {
  head_pan: 'Pan',
  head_tilt: 'Tilt',
  sho_pitch: 'Shoulder pitch',
  sho_roll: 'Shoulder roll',
  el_pitch: 'Forearm twist',
  el_yaw: 'Elbow bend',
  gripper: 'Gripper',
  hip_yaw: 'Hip twist',
  hip_roll: 'Hip roll',
  hip_pitch: 'Hip pitch',
  knee: 'Knee',
  ank_pitch: 'Ankle pitch',
  ank_roll: 'Ankle roll',
}

/** Human-readable name for a joint within its group, e.g. l_el_yaw → "Elbow bend". */
export function jointLabel(joint: string): string {
  return PART_LABELS[joint] ?? PART_LABELS[joint.slice(2)] ?? joint
}

/** Hardware stand pose (matches backend servo_config.STAND_PULSE). */
export const STAND_PULSES: Record<string, number> = {
  head_pan: 500, head_tilt: 500,
  l_sho_pitch: 835, r_sho_pitch: 165,
  l_sho_roll: 830, r_sho_roll: 170,
  l_el_pitch: 500, r_el_pitch: 500,
  l_el_yaw: 150, r_el_yaw: 850,
  l_gripper: 500, r_gripper: 500,
  l_hip_yaw: 500, r_hip_yaw: 500,
  l_hip_roll: 500, r_hip_roll: 500,
  l_hip_pitch: 350, r_hip_pitch: 650,
  l_knee: 500, r_knee: 500,
  l_ank_pitch: 640, r_ank_pitch: 360,
  l_ank_roll: 500, r_ank_roll: 500,
}
