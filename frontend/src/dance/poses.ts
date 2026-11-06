// Dance Game preset pose library.
//
// These are full-body servo poses ported from backend/app/robot/motions.py's
// MOTIONS registry, which before this game existed only as data for a dev CLI
// script (`main_sim_test`) — never reachable from the frontend. They are
// ported here (rather than fetched from the backend) because /set-pose
// already accepts any pulse dict, so no backend change is needed.
//
// A few of the source poses (thinker, superhero, warrior2, hand-raised,
// t-pose, muscles) omit head_pan/head_tilt entirely. Since /set-pose only
// touches joints present in the posted dict, an omitted joint would silently
// keep whatever the previous pose in the sequence left it at. head_pan/
// head_tilt: 500 (centre) is added to every pose below so each one is fully
// self-contained regardless of play order.
//
// "wave" in motions.py is a 9-frame animation, not a single pose. Its last
// frame is identical to the resting stand-arms position (it's the wind-down
// frame), so using it here would make the "Wave" block look just like "Stand".
// Frame 0 (arms raised, mid-wave) is used instead as a single representative
// pose. Playing the full animation is a documented future idea, not built here.
//
// Four source poses ask for more than the robot's geometry allows: an elbow
// folded until the forearm is inside the upper arm (superhero, muscles, wave,
// thinker), and in thinker the feet overlapping. The collision check stopped
// every move into them short. Those joints are eased off to just clear of
// contact (a few degrees; marked "eased" below), so each pose is reached in
// full. backend/tests/test_dance_poses.py checks every pose here is clear.

export type DancePoseId =
  | 'stand'
  | 't-pose'
  | 'dab'
  | 'superhero'
  | 'thinker'
  | 'muscles'
  | 'hand-raised'
  | 'warrior2'
  | 'wave'

export interface DancePoseDef {
  id: DancePoseId
  label: string
  emoji: string
  /** Hardware servo pulses (0-1000, 500 = centre), full body. Same format as robot/motions.py. */
  robotPulses: Record<string, number>
}

export const DANCE_POSES: DancePoseDef[] = [
  {
    id: 'stand',
    label: 'Stand',
    emoji: '🧍',
    // motions.py STAND_PULSE
    robotPulses: {
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
    },
  },
  {
    id: 't-pose',
    label: 'T-Pose',
    emoji: '🤷',
    // motions.py T_POSE_PULSE (head_pan/head_tilt added, see file header)
    robotPulses: {
      l_ank_roll: 499, r_ank_roll: 501,
      l_ank_pitch: 638, r_ank_pitch: 358,
      l_knee: 504, r_knee: 495,
      l_hip_pitch: 348, r_hip_pitch: 648,
      l_hip_roll: 498, r_hip_roll: 498,
      l_hip_yaw: 499, r_hip_yaw: 499,
      l_sho_pitch: 718, r_sho_pitch: 294,
      l_sho_roll: 513, r_sho_roll: 520,
      l_el_pitch: 498, r_el_pitch: 500,
      l_el_yaw: 504, r_el_yaw: 454,
      l_gripper: 499, r_gripper: 499,
      head_pan: 500, head_tilt: 500,
    },
  },
  {
    id: 'dab',
    label: 'Dab',
    emoji: '🤸',
    // motions.py DAB_PULSE
    robotPulses: {
      l_ank_roll: 500, r_ank_roll: 500,
      l_ank_pitch: 720, r_ank_pitch: 280,
      l_knee: 650, r_knee: 350,
      l_hip_pitch: 240, r_hip_pitch: 755,
      l_hip_roll: 500, r_hip_roll: 500,
      l_hip_yaw: 500, r_hip_yaw: 500,
      l_sho_pitch: 835, r_sho_pitch: 675,
      l_sho_roll: 585, r_sho_roll: 225,
      l_el_pitch: 500, r_el_pitch: 120,
      l_el_yaw: 465, r_el_yaw: 890,
      l_gripper: 500, r_gripper: 500,
      head_pan: 500, head_tilt: 500,
    },
  },
  {
    id: 'superhero',
    label: 'Superhero',
    emoji: '🦸',
    // motions.py SUPERHERO_PULSE (head_pan/head_tilt added, see file header)
    robotPulses: {
      l_ank_roll: 499, r_ank_roll: 501,
      l_ank_pitch: 639, r_ank_pitch: 358,
      l_knee: 505, r_knee: 493,
      l_hip_pitch: 348, r_hip_pitch: 648,
      l_hip_roll: 498, r_hip_roll: 498,
      l_hip_yaw: 499, r_hip_yaw: 498,
      l_sho_pitch: 824, r_sho_pitch: 174,
      l_sho_roll: 704, r_sho_roll: 316,
      l_el_pitch: 652, r_el_pitch: 348,
      l_el_yaw: 103, r_el_yaw: 898, // eased from 90 / 907
      l_gripper: 504, r_gripper: 499,
      head_pan: 500, head_tilt: 500,
    },
  },
  {
    id: 'thinker',
    label: 'Thinker',
    emoji: '🤔',
    // motions.py THINKER_PULSE (head_pan/head_tilt added, see file header)
    robotPulses: {
      l_ank_roll: 499, r_ank_roll: 494,
      l_ank_pitch: 641, r_ank_pitch: 356,
      l_knee: 476, r_knee: 502,
      l_hip_pitch: 351, r_hip_pitch: 651,
      l_hip_roll: 501, r_hip_roll: 497,
      l_hip_yaw: 500, r_hip_yaw: 543, // r eased from 557
      l_sho_pitch: 518, r_sho_pitch: 436,
      l_sho_roll: 784, r_sho_roll: 171,
      l_el_pitch: 655, r_el_pitch: 162,
      l_el_yaw: 104, r_el_yaw: 849, // l eased from 53
      l_gripper: 625, r_gripper: 499,
      head_pan: 500, head_tilt: 500,
    },
  },
  {
    id: 'muscles',
    label: 'Muscles',
    emoji: '💪',
    // motions.py MUSCLES_PULSE (head_pan/head_tilt added, see file header)
    robotPulses: {
      l_ank_roll: 499, r_ank_roll: 501,
      l_ank_pitch: 642, r_ank_pitch: 358,
      l_knee: 503, r_knee: 494,
      l_hip_pitch: 348, r_hip_pitch: 651,
      l_hip_roll: 499, r_hip_roll: 498,
      l_hip_yaw: 502, r_hip_yaw: 501,
      l_sho_pitch: 348, r_sho_pitch: 654,
      l_sho_roll: 601, r_sho_roll: 450,
      l_el_pitch: 507, r_el_pitch: 498,
      l_el_yaw: 63, r_el_yaw: 905, // l eased from 26
      l_gripper: 610, r_gripper: 374,
      head_pan: 500, head_tilt: 500,
    },
  },
  {
    id: 'hand-raised',
    label: 'Hand Raised',
    emoji: '🙋',
    // motions.py HANDS_UP_PULSE (head_pan/head_tilt added, see file header)
    robotPulses: {
      l_ank_roll: 499, r_ank_roll: 502,
      l_ank_pitch: 638, r_ank_pitch: 354,
      l_knee: 502, r_knee: 490,
      l_hip_pitch: 346, r_hip_pitch: 649,
      l_hip_roll: 500, r_hip_roll: 498,
      l_hip_yaw: 502, r_hip_yaw: 498,
      l_sho_pitch: 185, r_sho_pitch: 841,
      l_sho_roll: 729, r_sho_roll: 254,
      l_el_pitch: 625, r_el_pitch: 413,
      l_el_yaw: 170, r_el_yaw: 770,
      l_gripper: 499, r_gripper: 499,
      head_pan: 500, head_tilt: 500,
    },
  },
  {
    id: 'warrior2',
    label: 'Warrior',
    emoji: '🥋',
    // motions.py WARRIOR_PULSE (head_pan/head_tilt added, see file header)
    robotPulses: {
      l_ank_roll: 505, r_ank_roll: 498,
      l_ank_pitch: 780, r_ank_pitch: 572,
      l_knee: 428, r_knee: 559,
      l_hip_pitch: 604, r_hip_pitch: 750,
      l_hip_roll: 509, r_hip_roll: 501,
      l_hip_yaw: 561, r_hip_yaw: 557,
      l_sho_pitch: 981, r_sho_pitch: 662,
      l_sho_roll: 815, r_sho_roll: 211,
      l_el_pitch: 506, r_el_pitch: 534,
      l_el_yaw: 481, r_el_yaw: 531,
      l_gripper: 499, r_gripper: 499,
      head_pan: 500, head_tilt: 500,
    },
  },
  {
    id: 'wave',
    label: 'Wave',
    emoji: '👋',
    // motions.py WAVE, frame 0 only (see file header for why)
    robotPulses: {
      l_ank_roll: 500, r_ank_roll: 500,
      l_ank_pitch: 640, r_ank_pitch: 360,
      l_knee: 500, r_knee: 500,
      l_hip_pitch: 330, r_hip_pitch: 670,
      l_hip_roll: 500, r_hip_roll: 500,
      l_hip_yaw: 500, r_hip_yaw: 500,
      l_sho_pitch: 1000, r_sho_pitch: 0,
      l_sho_roll: 500, r_sho_roll: 500,
      l_el_pitch: 500, r_el_pitch: 500,
      l_el_yaw: 268, r_el_yaw: 940, // r eased from 1000
      l_gripper: 500, r_gripper: 500,
      head_pan: 500, head_tilt: 500,
    },
  },
]

export const DANCE_POSE_BY_ID: Record<DancePoseId, DancePoseDef> = Object.fromEntries(
  DANCE_POSES.map((p) => [p.id, p]),
) as Record<DancePoseId, DancePoseDef>

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
