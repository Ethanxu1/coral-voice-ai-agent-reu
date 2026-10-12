// A set of three moves the game can be played with: the standard arm poses, or
// the child's own custom moves. The game, the cheat sheet and the classifier all
// take a GestureSet, so they work the same for both.

import type { MatchOptions, PoseTemplate, PoseVector } from '../pose/poseSimilarity'
import {
  DETECTION,
  GESTURES,
  GESTURE_TEMPLATES,
  figureFromPose,
  type GestureDef,
  type GestureId,
} from './gestures'

export interface GestureSet {
  kind: 'standard' | 'custom'
  /** Rock, paper, scissors, in that order. */
  gestures: GestureDef[]
  byId: Record<GestureId, GestureDef>
  templates: PoseTemplate[]
  detection: MatchOptions
}

function makeSet(kind: GestureSet['kind'], gestures: GestureDef[], templates: PoseTemplate[], detection: MatchOptions): GestureSet {
  const byId = Object.fromEntries(gestures.map((g) => [g.id, g])) as Record<GestureId, GestureDef>
  return { kind, gestures, byId, templates, detection }
}

export const STANDARD_SET = makeSet('standard', GESTURES, GESTURE_TEMPLATES, DETECTION)

/** One recorded custom move: the child's pose and the pose the robot reached copying it. */
export interface CustomMove {
  pose: PoseVector
  robotPulses: Record<string, number>
}

/**
 * Custom moves are matched against poses recorded from the same camera, so a
 * mirrored camera can't confuse them. Turning the mirror check off also lets a
 * child use "left arm up" and "right arm up" as two different moves.
 */
export const CUSTOM_DETECTION: MatchOptions = { ...DETECTION, cameraMayBeMirrored: false }

export function customSet(moves: Record<GestureId, CustomMove>): GestureSet {
  const gestures = GESTURES.map((g) => ({
    ...g,
    tagline: `Your own ${g.label} move.`,
    steps: [],
    figure: figureFromPose(moves[g.id].pose),
    robotPulses: moves[g.id].robotPulses,
  }))
  const templates = GESTURES.map((g) => ({ id: g.id, joints: moves[g.id].pose }))
  return makeSet('custom', gestures, templates, CUSTOM_DETECTION)
}
