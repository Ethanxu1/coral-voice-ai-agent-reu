// Generic pose matching: "which of these reference poses is the person making?"
//
// Not tied to any game. A game supplies a list of reference poses (templates) and
// gets back a similarity score for each one, plus the best match if it is
// convincing enough. Rock-Paper-Scissors uses it today; any future game that asks
// "is the player doing pose X?" can use the same functions.
//
// How it works
//   1. normalizePose() turns the camera's body landmarks into a size- and
//      position-independent description: joint positions measured from the middle
//      of the shoulders, in units of shoulder width. So it does not matter how far
//      the person is from the camera, or where they stand in the picture.
//   2. poseSimilarity() compares two such descriptions. It averages how far apart
//      the matching joints are (in shoulder widths) and turns that into a score
//      from 0 (nothing alike) to 1 (identical).
//   3. matchPose() scores a live pose against every template and picks the best,
//      but only if it is similar enough and clearly ahead of the runner-up.
//
// Only the joints you ask for are compared (default: elbows and wrists), so hips,
// legs or a face never have to be in view unless a game needs them.

import type { Landmark } from '../types/pose'

export type JointName =
  | 'nose'
  | 'leftShoulder'
  | 'rightShoulder'
  | 'leftElbow'
  | 'rightElbow'
  | 'leftWrist'
  | 'rightWrist'
  | 'leftHip'
  | 'rightHip'
  | 'leftKnee'
  | 'rightKnee'
  | 'leftAnkle'
  | 'rightAnkle'

/** MediaPipe pose landmark index for each joint. */
export const JOINT_INDEX: Record<JointName, number> = {
  nose: 0,
  leftShoulder: 11,
  rightShoulder: 12,
  leftElbow: 13,
  rightElbow: 14,
  leftWrist: 15,
  rightWrist: 16,
  leftHip: 23,
  rightHip: 24,
  leftKnee: 25,
  rightKnee: 26,
  leftAnkle: 27,
  rightAnkle: 28,
}

/** Joints that every pose needs, to work out the position and scale. */
const ANCHORS: JointName[] = ['leftShoulder', 'rightShoulder']

/** Default joints to compare: the arms. */
export const ARM_JOINTS: JointName[] = ['leftElbow', 'rightElbow', 'leftWrist', 'rightWrist']

/**
 * A pose, normalized: [x, y] per joint, measured from the middle of the shoulders
 * in shoulder widths. x grows to the right of the image, y grows downward.
 */
export type PoseVector = Partial<Record<JointName, [number, number]>>

export interface PoseTemplate {
  id: string
  joints: PoseVector
}

export interface PoseOptions {
  /** Joints to compare. Default: elbows and wrists. */
  joints?: JointName[]
  /** Minimum landmark visibility to trust a joint. Default 0.5. */
  minVisibility?: number
  /**
   * Width / height of the camera image. Landmarks x and y are fractions of the
   * frame, so x is scaled by this to keep distances true. Default 4/3.
   */
  aspect?: number
}

export interface SimilarityOptions {
  joints?: JointName[]
  /**
   * Average joint distance (in shoulder widths) at which the score reaches 0.
   * Smaller = pickier. Default 1.2.
   */
  maxDistance?: number
  /**
   * The camera image may be mirrored (the person's left shows on the image's
   * left). Also tries the template with x flipped and keeps the better score.
   * Default false.
   */
  cameraMayBeMirrored?: boolean
  /**
   * Accept the left/right mirror-image version of the template too, e.g. a
   * "left hand up" pose done with the right hand. Default false.
   */
  allowMirroredGesture?: boolean
}

export interface MatchOptions extends PoseOptions, SimilarityOptions {
  /** Best score must reach this to count as a match. Default 0.6. */
  minSimilarity?: number
  /** Best score must beat the runner-up by this much, else it is ambiguous. Default 0.05. */
  margin?: number
}

export interface MatchResult {
  /** Similarity (0-1) of the live pose to every template, by template id. */
  scores: Record<string, number>
  /** The matching template, or null if none is similar enough or it is a tie. */
  best: { id: string; similarity: number } | null
}

const DEFAULTS = {
  minVisibility: 0.5,
  aspect: 4 / 3,
  maxDistance: 1.2,
  minSimilarity: 0.6,
  margin: 0.05,
}

const isVisible = (lm: Landmark | undefined, min: number) => !!lm && lm.visibility >= min

/**
 * Describe the pose in `body` independent of size and position. Returns null if
 * the shoulders, or any requested joint, can't be seen well enough.
 */
export function normalizePose(body: Landmark[], opts: PoseOptions = {}): PoseVector | null {
  const joints = opts.joints ?? ARM_JOINTS
  const minVisibility = opts.minVisibility ?? DEFAULTS.minVisibility
  const aspect = opts.aspect ?? DEFAULTS.aspect

  const needed = new Set<JointName>([...ANCHORS, ...joints])
  for (const name of needed) {
    if (!isVisible(body[JOINT_INDEX[name]], minVisibility)) return null
  }

  // Work in "frame heights" so x and y have the same scale.
  const pos = (name: JointName): [number, number] => {
    const lm = body[JOINT_INDEX[name]]
    return [lm.x * aspect, lm.y]
  }
  const ls = pos('leftShoulder')
  const rs = pos('rightShoulder')
  const width = Math.hypot(ls[0] - rs[0], ls[1] - rs[1])
  if (width < 1e-3) return null
  const mid: [number, number] = [(ls[0] + rs[0]) / 2, (ls[1] + rs[1]) / 2]

  const out: PoseVector = {}
  for (const name of joints) {
    const p = pos(name)
    out[name] = [(p[0] - mid[0]) / width, (p[1] - mid[1]) / width]
  }
  return out
}

const FLIP: Partial<Record<JointName, JointName>> = {
  leftShoulder: 'rightShoulder',
  rightShoulder: 'leftShoulder',
  leftElbow: 'rightElbow',
  rightElbow: 'leftElbow',
  leftWrist: 'rightWrist',
  rightWrist: 'leftWrist',
  leftHip: 'rightHip',
  rightHip: 'leftHip',
  leftKnee: 'rightKnee',
  rightKnee: 'leftKnee',
  leftAnkle: 'rightAnkle',
  rightAnkle: 'leftAnkle',
}

/** The same pose with the image flipped left-right: every x changes sign. */
export function flipX(pose: PoseVector): PoseVector {
  const out: PoseVector = {}
  for (const [name, p] of Object.entries(pose) as [JointName, [number, number]][]) {
    out[name] = [-p[0], p[1]]
  }
  return out
}

/** The mirror-image gesture: left and right swap and x flips (left hand up -> right hand up). */
export function mirrorGesture(pose: PoseVector): PoseVector {
  const out: PoseVector = {}
  for (const [name, p] of Object.entries(pose) as [JointName, [number, number]][]) {
    out[FLIP[name] ?? name] = [-p[0], p[1]]
  }
  return out
}

function similarityOnce(a: PoseVector, b: PoseVector, joints: JointName[], maxDistance: number): number {
  let total = 0
  let count = 0
  for (const name of joints) {
    const pa = a[name]
    const pb = b[name]
    if (!pa || !pb) continue
    total += Math.hypot(pa[0] - pb[0], pa[1] - pb[1])
    count++
  }
  if (count === 0) return 0
  return Math.max(0, 1 - total / count / maxDistance)
}

/**
 * How alike two normalized poses are, from 0 (nothing alike) to 1 (identical).
 * Only joints present in both are compared.
 */
export function poseSimilarity(a: PoseVector, b: PoseVector, opts: SimilarityOptions = {}): number {
  const joints = opts.joints ?? ARM_JOINTS
  const maxDistance = opts.maxDistance ?? DEFAULTS.maxDistance
  const candidates = [b]
  if (opts.cameraMayBeMirrored) candidates.push(flipX(b))
  if (opts.allowMirroredGesture) candidates.push(mirrorGesture(b))
  return Math.max(...candidates.map((c) => similarityOnce(a, c, joints, maxDistance)))
}

/**
 * Score the live pose against every template and pick the best one.
 *
 * `best` is null when the pose can't be read (joints not visible), when nothing
 * is similar enough, or when the top two templates are too close to call.
 */
export function matchPose(
  body: Landmark[],
  templates: PoseTemplate[],
  opts: MatchOptions = {},
): MatchResult {
  const live = normalizePose(body, opts)
  if (!live) return { scores: {}, best: null }

  const scores: Record<string, number> = {}
  for (const t of templates) scores[t.id] = poseSimilarity(live, t.joints, opts)

  const ranked = Object.entries(scores).sort((x, y) => y[1] - x[1])
  if (ranked.length === 0) return { scores, best: null }

  const minSimilarity = opts.minSimilarity ?? DEFAULTS.minSimilarity
  const margin = opts.margin ?? DEFAULTS.margin
  const [topId, topScore] = ranked[0]
  const runnerUp = ranked[1]?.[1] ?? 0
  if (topScore < minSimilarity || topScore - runnerUp < margin) return { scores, best: null }
  return { scores, best: { id: topId, similarity: topScore } }
}
