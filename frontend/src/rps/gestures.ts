// Rock-Paper-Scissors gesture definitions.
//
// This is the one place to decide what "rock", "paper" and "scissors" look like.
// Everything else (the Learn pictures, the simulator robot's pose, and the
// camera detection in the game) reads from here.
//
// Gestures are arm poses rather than hand shapes because the AiNex robot has no
// fingers. They only need the child's shoulders and arms in the camera frame
// (hips are not required).

export type GestureId = 'rock' | 'paper' | 'scissors'

export interface GestureDef {
  id: GestureId
  label: string
  emoji: string
  /** One line shown under the title in Learn. */
  tagline: string
  /** Step-by-step teaching text shown in Learn. */
  steps: string[]
  /**
   * Stick-figure drawing for Learn, in a 100x100 box. The head is at (50, 18)
   * and the shoulders at (36, 38) and (64, 38). Points are the child's
   * elbows and hands as seen by the viewer.
   */
  figure: {
    leftElbow: [number, number]
    leftHand: [number, number]
    rightElbow: [number, number]
    rightHand: [number, number]
  }
  /**
   * What the simulator robot does. Hardware servo pulses (0-1000, 500 = centre)
   * for the arm joints only, same format as robot/motions.py.
   */
  robotPulses: Record<string, number>
}

export const GESTURES: GestureDef[] = [
  {
    id: 'rock',
    label: 'Rock',
    emoji: '✊',
    tagline: 'Cross your arms over your chest, like a closed fist.',
    steps: [
      'Stand facing the camera.',
      'Bend both elbows and bring your hands up to your chest.',
      'Cross your arms in an X so each hand is on the opposite side.',
    ],
    figure: {
      leftElbow: [30, 56],
      leftHand: [62, 44],
      rightElbow: [70, 56],
      rightHand: [38, 44],
    },
    robotPulses: {
      l_sho_pitch: 500,
      r_sho_pitch: 500,
      l_sho_roll: 900,
      r_sho_roll: 100,
      l_el_pitch: 500,
      r_el_pitch: 500,
      l_el_yaw: 40,
      r_el_yaw: 960,
    },
  },
  {
    id: 'paper',
    label: 'Paper',
    emoji: '✋',
    tagline: 'Stretch both arms straight out to the sides, like a flat sheet.',
    steps: [
      'Stand facing the camera.',
      'Lift both arms out to your sides.',
      'Keep them straight and level with your shoulders, like a letter T.',
    ],
    figure: {
      leftElbow: [14, 38],
      leftHand: [-4, 38],
      rightElbow: [86, 38],
      rightHand: [104, 38],
    },
    // T pose (motions.py T_POSE_PULSE, arms only).
    robotPulses: {
      l_sho_pitch: 718,
      r_sho_pitch: 294,
      l_sho_roll: 513,
      r_sho_roll: 520,
      l_el_pitch: 498,
      r_el_pitch: 500,
      l_el_yaw: 504,
      r_el_yaw: 454,
    },
  },
  {
    id: 'scissors',
    label: 'Scissors',
    emoji: '✌️',
    tagline: 'Raise both arms up high in a V, like the two blades.',
    steps: [
      'Stand facing the camera.',
      'Lift both arms up over your head.',
      'Spread them apart so your arms make a big V.',
    ],
    figure: {
      leftElbow: [24, 22],
      leftHand: [16, 4],
      rightElbow: [76, 22],
      rightHand: [84, 4],
    },
    robotPulses: {
      l_sho_pitch: 185,
      r_sho_pitch: 841,
      l_sho_roll: 729,
      r_sho_roll: 254,
      l_el_pitch: 625,
      r_el_pitch: 413,
      l_el_yaw: 170,
      r_el_yaw: 770,
    },
  },
]

export const GESTURE_BY_ID: Record<GestureId, GestureDef> = Object.fromEntries(
  GESTURES.map((g) => [g.id, g]),
) as Record<GestureId, GestureDef>

/**
 * Camera detection thresholds. Distances are in units of the child's shoulder
 * width, so they work at any distance from the camera.
 */
export const DETECTION = {
  /** Minimum landmark visibility to trust a shoulder or wrist. */
  minVisibility: 0.5,
  /** Rock: each wrist must be this far past the body's centre line, on the opposite side from its own shoulder. */
  rockCrossMargin: 0.1,
  /** Rock: wrists must be no more than this far above the shoulders. */
  rockMaxAboveShoulder: 0.6,
  /** Scissors: both wrists must be at least this far above the shoulders. */
  scissorsMinAboveShoulder: 0.7,
  /** Paper: each wrist must be at least this far out from the body's centre line. */
  paperMinSpread: 1.4,
  /** Paper: wrists must be within this far above or below the shoulders. */
  paperMaxVerticalOffset: 0.7,
}

/** Robot arms back to a relaxed stand. */
export const ROBOT_REST_PULSES: Record<string, number> = {
  l_sho_pitch: 835,
  r_sho_pitch: 165,
  l_sho_roll: 830,
  r_sho_roll: 170,
  l_el_pitch: 500,
  r_el_pitch: 500,
  l_el_yaw: 150,
  r_el_yaw: 850,
}

/** Who beats whom. */
export const BEATS: Record<GestureId, GestureId> = {
  rock: 'scissors',
  paper: 'rock',
  scissors: 'paper',
}
