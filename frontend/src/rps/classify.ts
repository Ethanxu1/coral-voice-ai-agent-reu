import type { Landmark } from '../types/pose'
import { matchPose } from '../pose/poseSimilarity'
import type { GestureId } from './gestures'
import { STANDARD_SET, type GestureSet } from './gestureSet'

/**
 * Which gesture is the child making? Scores the live pose against the set's
 * three reference poses with the generic matcher and returns the most similar
 * one, or null if none is convincing or the arms can't be seen.
 */
export function classifyGesture(body: Landmark[], set: GestureSet = STANDARD_SET): GestureId | null {
  return (matchPose(body, set.templates, set.detection).best?.id as GestureId | undefined) ?? null
}

/** Similarity (0-1) of the live pose to each gesture, or null if it can't be read. */
export function gestureScores(body: Landmark[], set: GestureSet = STANDARD_SET): Record<GestureId, number> | null {
  const { scores } = matchPose(body, set.templates, set.detection)
  return Object.keys(scores).length > 0 ? (scores as Record<GestureId, number>) : null
}
