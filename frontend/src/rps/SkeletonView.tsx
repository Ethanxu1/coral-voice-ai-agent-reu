import type { Landmark } from '../types/pose'

// MediaPipe pose landmark indices.
const NOSE = 0
const L_SHOULDER = 11
const R_SHOULDER = 12
const L_ELBOW = 13
const R_ELBOW = 14
const L_WRIST = 15
const R_WRIST = 16

const BONES: [number, number][] = [
  [L_SHOULDER, R_SHOULDER],
  [L_SHOULDER, L_ELBOW],
  [L_ELBOW, L_WRIST],
  [R_SHOULDER, R_ELBOW],
  [R_ELBOW, R_WRIST],
]

const JOINTS = [L_SHOULDER, R_SHOULDER, L_ELBOW, R_ELBOW, L_WRIST, R_WRIST]

const W = 640
const H = 480
const MIN_VISIBILITY = 0.5

const seen = (lm: Landmark | undefined) => !!lm && lm.visibility >= MIN_VISIBILITY

/** What the tracker needs before the robot can follow your arms. */
export function followReadiness(body: Landmark[]): { ok: boolean; message: string } {
  if (body.length <= R_WRIST) return { ok: false, message: "I can't see you yet." }
  if (!seen(body[L_SHOULDER]) || !seen(body[R_SHOULDER])) {
    return { ok: false, message: "I can't see both of your shoulders. Move into the middle of the picture." }
  }
  const arms = [L_ELBOW, R_ELBOW, L_WRIST, R_WRIST].filter((i) => !seen(body[i])).length
  if (arms > 0) {
    return { ok: false, message: "I can't see all of your arms. Raise them where the camera can see them." }
  }
  return { ok: true, message: 'I can see your head and both arms, so the robot can follow.' }
}

/**
 * The stick figure the pose tracker has built from the camera: where it thinks
 * each joint is. Joints it can't see well are drawn faded, so it's clear why a
 * robot isn't following.
 */
export default function SkeletonView({ landmarks }: { landmarks: Landmark[] }) {
  const has = landmarks.length > R_WRIST
  const px = (i: number): [number, number] => [landmarks[i].x * W, landmarks[i].y * H]

  return (
    <svg className="rps-skeleton" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Pose the tracker sees">
      {has && (
        <>
          {BONES.map(([a, b]) => {
            const ok = seen(landmarks[a]) && seen(landmarks[b])
            const [x1, y1] = px(a)
            const [x2, y2] = px(b)
            return (
              <line
                key={`${a}-${b}`}
                x1={x1}
                y1={y1}
                x2={x2}
                y2={y2}
                className={ok ? 'rps-bone' : 'rps-bone faded'}
              />
            )
          })}
          {seen(landmarks[NOSE]) && (
            <circle cx={px(NOSE)[0]} cy={px(NOSE)[1]} r="22" className="rps-head" />
          )}
          {JOINTS.map((i) => {
            const [x, y] = px(i)
            return (
              <circle
                key={i}
                cx={x}
                cy={y}
                r={seen(landmarks[i]) ? 8 : 6}
                className={seen(landmarks[i]) ? 'rps-joint' : 'rps-joint faded'}
              />
            )
          })}
        </>
      )}
    </svg>
  )
}
