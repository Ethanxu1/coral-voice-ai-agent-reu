import type { Landmark } from '../types/pose'
import { matchPose } from '../pose/poseSimilarity'
import { DETECTION, GESTURE_TEMPLATES, type GestureId } from './gestures'

/**
 * Which gesture is the child making? Scores the live pose against the three
 * reference poses (see GESTURE_TEMPLATES) with the generic matcher and returns
 * the most similar one, or null if none is convincing or the arms can't be seen.
 */
export function classifyGesture(body: Landmark[]): GestureId | null {
  return (matchPose(body, GESTURE_TEMPLATES, DETECTION).best?.id as GestureId | undefined) ?? null
}

/** Similarity (0-1) of the live pose to each gesture, or null if it can't be read. */
export function gestureScores(body: Landmark[]): Record<GestureId, number> | null {
  const { scores } = matchPose(body, GESTURE_TEMPLATES, DETECTION)
  return Object.keys(scores).length > 0 ? (scores as Record<GestureId, number>) : null
}
