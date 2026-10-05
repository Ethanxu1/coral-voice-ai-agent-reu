import type { Landmark } from '../types/pose'
import { DETECTION, type GestureId } from './gestures'

// MediaPipe pose landmark indices.
const L_SHOULDER = 11
const R_SHOULDER = 12
const L_WRIST = 15
const R_WRIST = 16

/**
 * Work out which gesture the child is making from one frame of body landmarks
 * (image coordinates, y grows downward). Returns null if the shoulders or wrists
 * aren't visible, or the arms don't match any gesture.
 *
 * Uses only the left/right landmark indices, never screen left/right, so it
 * doesn't matter whether the camera image is mirrored.
 */
export function classifyGesture(body: Landmark[]): GestureId | null {
  if (body.length <= R_WRIST) return null

  const ls = body[L_SHOULDER]
  const rs = body[R_SHOULDER]
  const lw = body[L_WRIST]
  const rw = body[R_WRIST]
  const ok = [ls, rs, lw, rw].every((p) => p.visibility >= DETECTION.minVisibility)
  if (!ok) return null

  const width = Math.abs(ls.x - rs.x)
  if (width < 1e-3) return null

  const midX = (ls.x + rs.x) / 2
  const shoulderY = (ls.y + rs.y) / 2

  // Signed offsets in shoulder widths: dx from the centre line, dy above the shoulders.
  const lDx = (lw.x - midX) / width
  const rDx = (rw.x - midX) / width
  const lDy = (shoulderY - lw.y) / width
  const rDy = (shoulderY - rw.y) / width
  const lSide = Math.sign(ls.x - midX)
  const rSide = Math.sign(rs.x - midX)

  const crossed =
    lDx * lSide < -DETECTION.rockCrossMargin && rDx * rSide < -DETECTION.rockCrossMargin
  if (crossed && lDy < DETECTION.rockMaxAboveShoulder && rDy < DETECTION.rockMaxAboveShoulder) {
    return 'rock'
  }

  if (lDy > DETECTION.scissorsMinAboveShoulder && rDy > DETECTION.scissorsMinAboveShoulder) {
    return 'scissors'
  }

  const spread = Math.abs(lDx) > DETECTION.paperMinSpread && Math.abs(rDx) > DETECTION.paperMinSpread
  const level =
    Math.abs(lDy) < DETECTION.paperMaxVerticalOffset && Math.abs(rDy) < DETECTION.paperMaxVerticalOffset
  if (spread && level) return 'paper'

  return null
}
