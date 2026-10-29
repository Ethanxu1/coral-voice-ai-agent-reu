import { useRef, type RefObject } from 'react'
import { LiveStream } from '../components/LiveStream'
import type { Landmark } from '../types/pose'
import { LM, seen } from './bodyFit'

const W = 640
const H = 480
/** Share of the way each frame moves a joint toward its new position: takes the jitter out, keeps up with real moves. */
const SMOOTHING = 0.45
const NEUTRAL = '#FFF1E8'

/** Landmarks eased frame to frame, so the drawing doesn't shake when the child holds still. */
function useSmoothedLandmarks(body: Landmark[]): Landmark[] {
  const prev = useRef<Landmark[]>([])
  const out = body.map((lm, i) => {
    const p = prev.current[i]
    return p ? { ...lm, x: p.x + SMOOTHING * (lm.x - p.x), y: p.y + SMOOTHING * (lm.y - p.y) } : lm
  })
  prev.current = out
  return out
}

/**
 * CORAL's eye: what the robot sees, drawn as a big chunky stick figure that
 * reads from across the room. Faint, flickering limbs are ones it isn't sure
 * of; the figure fills with a move's colour once CORAL recognises it. While the child gets in place
 * (`fits` set), the frame glows green once their upper body is in view.
 */
export default function CoralEye({
  body,
  color,
  fits,
  open,
  frameRef,
}: {
  body: Landmark[]
  /** The recognised move's colour, if any. */
  color: string | null
  /** Getting in place: is the child's upper body in view? Undefined once the game is on. */
  fits?: boolean
  /** Closed at the start screen; it opens when the game begins. */
  open: boolean
  /** The eye's outer frame, for whoever needs its position (the beam from CORAL's head). */
  frameRef?: RefObject<HTMLDivElement>
}) {
  const smooth = useSmoothedLandmarks(body)
  return (
    <div ref={frameRef} className={`eye ${open ? 'open' : ''} ${fits === undefined ? '' : fits ? 'fits' : 'placing'}`}>
      <div className="eye-lens">
        <svg viewBox={`0 0 ${W} ${H}`} className="eye-svg" role="img" aria-label="What CORAL sees">
          <Skeleton lm={smooth} color={color ?? NEUTRAL} />
        </svg>
        <div className="eye-cam">
          <LiveStream badge={false} />
        </div>
      </div>
    </div>
  )
}

/** Head, neck, shoulders, arms and a torso: only the joints the game uses, drawn thick. */
function Skeleton({ lm, color }: { lm: Landmark[]; color: string }) {
  const ls = lm[LM.lShoulder]
  const rs = lm[LM.rShoulder]
  if (lm.length <= LM.rWrist || !seen(ls) || !seen(rs)) return null

  const px = (p: { x: number; y: number }): [number, number] => [p.x * W, p.y * H]
  const sw = Math.hypot((ls.x - rs.x) * W, (ls.y - rs.y) * H)
  const stroke = Math.min(34, Math.max(12, sw * 0.24))
  const mid = { x: (ls.x + rs.x) / 2, y: (ls.y + rs.y) / 2 }
  const lh = lm[LM.lHip]
  const rh = lm[LM.rHip]
  const hip = seen(lh) && seen(rh) ? { x: (lh.x + rh.x) / 2, y: (lh.y + rh.y) / 2 } : { x: mid.x, y: mid.y + (sw * 1.3) / H }
  const nose = lm[LM.nose]
  const head = seen(nose) ? nose : { x: mid.x, y: mid.y - (sw * 0.8) / H }

  const bone = (a: { x: number; y: number }, b: { x: number; y: number }, sure: boolean, key: string) => {
    const [x1, y1] = px(a)
    const [x2, y2] = px(b)
    return <line key={key} x1={x1} y1={y1} x2={x2} y2={y2} className={sure ? '' : 'unsure'} />
  }
  const arm = (s: Landmark, e: number, w: number, side: string) => [
    bone(s, lm[e], seen(lm[e]), `${side}u`),
    bone(lm[e], lm[w], seen(lm[e]) && seen(lm[w]), `${side}f`),
  ]

  return (
    <g className="eye-skel" style={{ stroke: color, fill: color, strokeWidth: stroke }}>
      {bone(mid, hip, true, 'torso')}
      {bone(mid, head, seen(nose), 'neck')}
      {bone(ls, rs, true, 'shoulders')}
      {arm(ls, LM.lElbow, LM.lWrist, 'l')}
      {arm(rs, LM.rElbow, LM.rWrist, 'r')}
      {[LM.lWrist, LM.rWrist].map((i) => (
        <circle key={i} cx={px(lm[i])[0]} cy={px(lm[i])[1]} r={stroke * 0.85} className={seen(lm[i]) ? '' : 'unsure'} />
      ))}
      <circle cx={px(head)[0]} cy={px(head)[1]} r={sw * 0.3} className={`head ${seen(nose) ? '' : 'unsure'}`} />
    </g>
  )
}
