import type { GestureDef, GestureId } from './gestures'

/** Each move's colour: its badge, its countdown word, and the skeleton once the camera sees it. */
export const MOVE_COLOR: Record<GestureId, string> = {
  rock: '#8B5CF6',
  paper: '#0EA5A4',
  scissors: '#F59E0B',
}

/** Same layout as GestureFigure, so a custom move's figure fits too. */
const HEAD: [number, number] = [50, 16]
const L_SHOULDER: [number, number] = [36, 38]
const R_SHOULDER: [number, number] = [64, 38]

/**
 * A chunky, friendly drawing of a move: a round-headed kid with thick arms in
 * the move's colour. Drawn from the gesture's `figure`, so it always matches
 * what the camera checks for (and works for custom moves).
 */
export default function PoseArt({ gesture, color }: { gesture: Pick<GestureDef, 'id' | 'label' | 'figure'>; color?: string }) {
  const { leftElbow, leftHand, rightElbow, rightHand } = gesture.figure
  const arm = color ?? MOVE_COLOR[gesture.id]
  const limb = (pts: [number, number][]) => pts.map((p) => p.join(',')).join(' ')
  return (
    <svg className="pose-art" viewBox="-14 -10 128 122" role="img" aria-label={gesture.label}>
      {/* legs and body */}
      <g stroke="#3B2A4A" strokeWidth="11" strokeLinecap="round" strokeLinejoin="round" fill="none">
        <polyline points="43,74 39,100" />
        <polyline points="57,74 61,100" />
      </g>
      <rect x="35" y="32" width="30" height="46" rx="14" fill="#3B2A4A" />
      {/* arms */}
      <g stroke={arm} strokeWidth="11" strokeLinecap="round" strokeLinejoin="round" fill="none">
        <polyline points={limb([L_SHOULDER, leftElbow, leftHand])} />
        <polyline points={limb([R_SHOULDER, rightElbow, rightHand])} />
      </g>
      <circle cx={leftHand[0]} cy={leftHand[1]} r="7" fill={arm} stroke="#fff" strokeWidth="2.5" />
      <circle cx={rightHand[0]} cy={rightHand[1]} r="7" fill={arm} stroke="#fff" strokeWidth="2.5" />
      {/* head and a smile */}
      <circle cx={HEAD[0]} cy={HEAD[1]} r="13" fill="#FFD9C2" stroke="#3B2A4A" strokeWidth="3.5" />
      <circle cx="45.5" cy="15" r="1.9" fill="#3B2A4A" />
      <circle cx="54.5" cy="15" r="1.9" fill="#3B2A4A" />
      <path d="M45.5 20.5 Q50 24.5 54.5 20.5" stroke="#3B2A4A" strokeWidth="2.2" strokeLinecap="round" fill="none" />
    </svg>
  )
}
