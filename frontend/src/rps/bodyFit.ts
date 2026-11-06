// Where the child stands in CORAL's camera picture: is their upper body in
// view, and has an arm left the picture (for CORAL's "step back" tip)? Pure functions
// over MediaPipe pose landmarks (x, y from 0 to 1 across the camera frame).

import type { Landmark } from '../types/pose'

// MediaPipe pose landmark indices.
export const LM = {
  nose: 0,
  lShoulder: 11,
  rShoulder: 12,
  lElbow: 13,
  rElbow: 14,
  lWrist: 15,
  rWrist: 16,
  lHip: 23,
  rHip: 24,
} as const

const MIN_VISIBILITY = 0.5
export const seen = (lm: Landmark | undefined) => !!lm && lm.visibility >= MIN_VISIBILITY

/** Shoulder width (share of frame) above which the child is too close for wide moves. */
const TOO_CLOSE = 0.5
/** Below this the child is so far away the tracker gets shaky. */
const TOO_FAR = 0.07
/** The shoulders' midpoint must be within this of the middle of the picture. */
const CENTRE_SLACK = 0.2
/** A joint this close to an edge is treated as leaving the picture. */
const EDGE = 0.03

export type Fit = 'away' | 'far' | 'close' | 'side' | 'fit'

/**
 * Is the child placed so CORAL can read their moves? Only the upper body
 * counts: head and shoulders in view, roughly centred, not right up at the
 * camera. Arms resting below the picture are fine; every move raises them into
 * view, and an arm that leaves the picture during a move shows as an edge pulse.
 */
export function bodyFit(body: Landmark[]): Fit {
  const ls = body[LM.lShoulder]
  const rs = body[LM.rShoulder]
  if (body.length <= LM.rWrist || !seen(ls) || !seen(rs) || !seen(body[LM.nose])) return 'away'
  const width = Math.abs(ls.x - rs.x)
  if (width > TOO_CLOSE) return 'close'
  if (width < TOO_FAR) return 'far'
  if (Math.abs((ls.x + rs.x) / 2 - 0.5) > CENTRE_SLACK) return 'side'
  return 'fit'
}

export type Edge = 'left' | 'right' | 'top'

/** Off the bottom doesn't count: every move raises the arms, so hands at rest below the picture are fine. */
const inside = (lm: Landmark) => lm.x > EDGE && lm.x < 1 - EDGE && lm.y > EDGE

/**
 * The edges of the picture an elbow or hand has gone past. MediaPipe still
 * guesses positions for joints outside the frame, so the nearest edge to that
 * guess is where the arm went. A faint joint inside the picture (hidden behind
 * the body, say) is not counted: it is drawn faint instead.
 */
export function offEdges(body: Landmark[]): Edge[] {
  if (body.length <= LM.rWrist || !seen(body[LM.lShoulder]) || !seen(body[LM.rShoulder])) return []
  const edges = new Set<Edge>()
  for (const i of [LM.lElbow, LM.rElbow, LM.lWrist, LM.rWrist]) {
    const lm = body[i]
    if (!lm || inside(lm)) continue
    const near: [Edge, number][] = [
      ['left', lm.x],
      ['right', 1 - lm.x],
      ['top', lm.y],
    ]
    edges.add(near.reduce((a, b) => (b[1] < a[1] ? b : a))[0])
  }
  return [...edges]
}
