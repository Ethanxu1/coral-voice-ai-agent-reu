// Rock-Paper-Scissors gesture definitions.
//
// This is the one place to decide what "rock", "paper" and "scissors" look like.
// Everything else (the Learn pictures, the simulator robot's pose, and the
// camera detection in the game) reads from here.
//
// Gestures are arm poses rather than hand shapes because the AiNex robot has no
// fingers. They only need the child's shoulders and arms in the camera frame
// (hips are not required).
//
// How the camera decides which gesture the child is making: each gesture's
// `figure` below doubles as its reference pose. The generic matcher in
// pose/poseSimilarity.ts scores the live pose against all three and picks the
// most similar one.

import type { PoseTemplate, PoseVector } from '../pose/poseSimilarity'

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
   * and the shoulders at (36, 38) and (64, 38) (28 wide). Points are the child's
   * elbows and hands as seen by the viewer. Also the gesture's reference pose
   * for camera detection, so keep the arm lengths realistic: about 22 for the
   * upper arm and 21 for the forearm.
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
      leftElbow: [34, 57],
      leftHand: [54, 52],
      rightElbow: [66, 57],
      rightHand: [46, 52],
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
      leftHand: [-7, 38],
      rightElbow: [86, 38],
      rightHand: [107, 38],
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
      leftElbow: [27, 18],
      leftHand: [18, -1],
      rightElbow: [73, 18],
      rightHand: [82, -1],
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

/** Shoulder centre and width inside the `figure` drawing, used to normalize it. */
const FIGURE_SHOULDER_MID: [number, number] = [50, 38]
const FIGURE_SHOULDER_WIDTH = 28

/** A gesture's reference pose, in the form the pose matcher compares against. */
function figureToPose(figure: GestureDef['figure']): PoseVector {
  const norm = (p: [number, number]): [number, number] => [
    (p[0] - FIGURE_SHOULDER_MID[0]) / FIGURE_SHOULDER_WIDTH,
    (p[1] - FIGURE_SHOULDER_MID[1]) / FIGURE_SHOULDER_WIDTH,
  ]
  // The drawing is "as seen by the viewer", and the camera sees the child facing
  // it, so the viewer's left is the child's right.
  return {
    rightElbow: norm(figure.leftElbow),
    rightWrist: norm(figure.leftHand),
    leftElbow: norm(figure.rightElbow),
    leftWrist: norm(figure.rightHand),
  }
}

export const GESTURE_TEMPLATES: PoseTemplate[] = GESTURES.map((g) => ({
  id: g.id,
  joints: figureToPose(g.figure),
}))

/**
 * Camera detection settings, passed to the generic pose matcher. Distances are
 * in shoulder widths, so they work at any distance from the camera.
 */
export const DETECTION = {
  /** Minimum landmark visibility to trust a shoulder, elbow or wrist. */
  minVisibility: 0.5,
  /** Average joint distance at which similarity falls to 0. Smaller = pickier. */
  maxDistance: 1.2,
  /** The best gesture must be at least this similar (0-1) to count. */
  minSimilarity: 0.72,
  /** The best gesture must beat the second best by this much, else it is a tie. */
  margin: 0.05,
  /** Don't depend on whether the camera image is mirrored. */
  cameraMayBeMirrored: true,
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
