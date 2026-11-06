// The child's own rock, paper and scissors, recorded on the "Make your own moves"
// screen. Kept in memory for this browser session only (a page refresh clears
// them) until the team decides how game data should be stored.

import { poseSimilarity } from '../pose/poseSimilarity'
import { GESTURES, type GestureId } from './gestures'
import { CUSTOM_DETECTION, customSet, type CustomMove, type GestureSet } from './gestureSet'

/** Two custom moves at least this similar (0-1) are too alike to tell apart. */
export const MAX_MOVE_SIMILARITY = 0.6

let moves: Partial<Record<GestureId, CustomMove>> = {}

export function getCustomMoves(): Partial<Record<GestureId, CustomMove>> {
  return moves
}

export function saveCustomMove(id: GestureId, move: CustomMove): void {
  moves = { ...moves, [id]: move }
}

export function clearCustomMoves(): void {
  moves = {}
}

/** Pairs of recorded moves that are too alike for the camera to tell apart. */
export function tooSimilarPairs(
  current: Partial<Record<GestureId, CustomMove>> = moves,
): { a: GestureId; b: GestureId; similarity: number }[] {
  const ids = GESTURES.map((g) => g.id).filter((id) => current[id])
  const pairs: { a: GestureId; b: GestureId; similarity: number }[] = []
  for (let i = 0; i < ids.length; i++) {
    for (let j = i + 1; j < ids.length; j++) {
      const similarity = poseSimilarity(current[ids[i]]!.pose, current[ids[j]]!.pose, CUSTOM_DETECTION)
      if (similarity >= MAX_MOVE_SIMILARITY) pairs.push({ a: ids[i], b: ids[j], similarity })
    }
  }
  return pairs
}

/** The custom moves as a playable set, or null until all three are recorded and distinct. */
export function customGestureSet(): GestureSet | null {
  if (!GESTURES.every((g) => moves[g.id])) return null
  if (tooSimilarPairs().length > 0) return null
  return customSet(moves as Record<GestureId, CustomMove>)
}
