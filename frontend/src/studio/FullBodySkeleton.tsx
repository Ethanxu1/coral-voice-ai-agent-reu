import type { Landmark } from './types'

const BONES: readonly [number, number, string][] = [
  [11, 12, 'shoulders'],
  [11, 13, 'left-upper-arm'],
  [13, 15, 'left-lower-arm'],
  [12, 14, 'right-upper-arm'],
  [14, 16, 'right-lower-arm'],
  [11, 23, 'left-torso'],
  [12, 24, 'right-torso'],
  [23, 24, 'hips'],
  [23, 25, 'left-hip-left-knee'],
  [25, 27, 'left-knee-left-ankle'],
  [24, 26, 'right-hip-right-knee'],
  [26, 28, 'right-knee-right-ankle'],
]

const JOINTS = [0, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28] as const
const UPPER_BODY_BONES = BONES.slice(0, 5)
const UPPER_BODY_JOINTS = [0, 11, 12, 13, 14, 15, 16] as const

function valid(landmark: Landmark | undefined): landmark is Landmark {
  return Boolean(
    landmark &&
      Number.isFinite(landmark.x) &&
      Number.isFinite(landmark.y) &&
      Number.isFinite(landmark.visibility),
  )
}

export function FullBodySkeleton({
  landmarks,
  className,
  label = 'Full-body pose skeleton',
}: {
  landmarks: Landmark[]
  className?: string
  label?: string
}) {
  return <PoseSkeleton landmarks={landmarks} bones={BONES} joints={JOINTS} className={className} label={label} />
}

export function UpperBodySkeleton({
  landmarks,
  className,
  label = 'Upper-body pose skeleton',
}: {
  landmarks: Landmark[]
  className?: string
  label?: string
}) {
  return (
    <PoseSkeleton
      landmarks={landmarks}
      bones={UPPER_BODY_BONES}
      joints={UPPER_BODY_JOINTS}
      className={className}
      label={label}
    />
  )
}

function PoseSkeleton({
  landmarks,
  bones,
  joints,
  className,
  label,
}: {
  landmarks: Landmark[]
  bones: readonly [number, number, string][]
  joints: readonly number[]
  className?: string
  label: string
}) {
  return (
    <svg className={className} viewBox="0 0 100 100" role="img" aria-label={label}>
      {bones.map(([startIndex, endIndex, name]) => {
        const start = landmarks[startIndex]
        const end = landmarks[endIndex]
        if (!valid(start) || !valid(end)) return null
        const opacity = Math.max(0.15, Math.min(1, (start.visibility + end.visibility) / 2))
        return (
          <line
            key={name}
            data-testid={`bone-${name}`}
            x1={start.x * 100}
            y1={start.y * 100}
            x2={end.x * 100}
            y2={end.y * 100}
            pathLength={1}
            opacity={opacity}
          />
        )
      })}
      {joints.map((index) => {
        const joint = landmarks[index]
        if (!valid(joint)) return null
        return (
          <circle
            key={index}
            cx={joint.x * 100}
            cy={joint.y * 100}
            r={index === 0 ? 3.5 : 2.2}
            opacity={Math.max(0.15, Math.min(1, joint.visibility))}
          />
        )
      })}
    </svg>
  )
}
