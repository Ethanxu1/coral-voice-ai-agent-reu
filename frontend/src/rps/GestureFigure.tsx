import type { GestureDef } from './gestures'

const HEAD: [number, number] = [50, 18]
const L_SHOULDER: [number, number] = [36, 38]
const R_SHOULDER: [number, number] = [64, 38]
const L_HIP: [number, number] = [42, 72]
const R_HIP: [number, number] = [58, 72]

const line = (a: [number, number], b: [number, number]) => (
  <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} />
)

/** Stick-figure picture that shows how to make a gesture. */
export default function GestureFigure({ gesture }: { gesture: GestureDef }) {
  const { leftElbow, leftHand, rightElbow, rightHand } = gesture.figure
  return (
    <svg
      className="rps-figure"
      viewBox="-10 -4 120 110"
      role="img"
      aria-label={`How to make ${gesture.label}`}
    >
      <g stroke="currentColor" strokeWidth="4" strokeLinecap="round" fill="none">
        <circle cx={HEAD[0]} cy={HEAD[1]} r="9" />
        {line([50, 27], [50, 72])}
        {line(L_SHOULDER, R_SHOULDER)}
        {line(L_SHOULDER, leftElbow)}
        {line(leftElbow, leftHand)}
        {line(R_SHOULDER, rightElbow)}
        {line(rightElbow, rightHand)}
        {line(L_HIP, [38, 100])}
        {line(R_HIP, [62, 100])}
        {line(L_HIP, R_HIP)}
      </g>
      <circle cx={leftHand[0]} cy={leftHand[1]} r="4" className="rps-figure-hand" />
      <circle cx={rightHand[0]} cy={rightHand[1]} r="4" className="rps-figure-hand" />
    </svg>
  )
}
