// The popup shown while a move block's stick figure is hovered: CORAL in 3D,
// struck in that pose (computed by the server on scratch state; the live sim
// doesn't move).

import { useEffect, useRef, useState } from 'react'
import RobotViewer from '../components/RobotViewer'
import { previewPose } from '../api/poseDesign'
import { danceMove } from './poses'

/** A hovered stick figure: which pose, and where its icon is on screen. */
export interface PoseHover {
  pose: string
  rect: DOMRect
}

/** Card size (px, matches DanceGame.css .pose-preview) and its gap from the icon. */
const CARD_W = 300
const CARD_H = 290
const GAP = 14
const EDGE = 8
/** Camera field of view (degrees): room for arms raised over the head. */
const PREVIEW_FOV = 46

/** Pose id -> where every robot link would be in it. Poses don't change, so each is fetched once. */
const previews = new Map<string, Promise<Float32Array>>()

function preview(id: string, pulses: Record<string, number>): Promise<Float32Array> {
  let p = previews.get(id)
  if (!p) {
    p = previewPose(pulses)
    p.catch(() => previews.delete(id))
    previews.set(id, p)
  }
  return p
}

export default function PosePreview({ hover }: { hover: PoseHover | null }) {
  const [shown, setShown] = useState<{ pose: string; links: Float32Array } | null>(null)
  // The 3D viewer is mounted on the first hover and then kept, so its meshes load only once.
  const [used, setUsed] = useState(false)
  /** Where the card last was, so it fades out there instead of jumping away. */
  const lastRect = useRef<DOMRect | null>(null)
  if (hover) lastRect.current = hover.rect
  const move = hover && danceMove(hover.pose)

  useEffect(() => {
    if (!hover || !move) return
    setUsed(true)
    let current = true
    preview(hover.pose, move.robotPulses)
      .then((links) => current && setShown({ pose: hover.pose, links }))
      .catch((e) => console.warn('pose preview failed', e))
    return () => {
      current = false
    }
    // Only a different pose needs a new preview, not the icon moving on screen.
  }, [hover?.pose])

  if (!used) return null
  const visible = !!move
  const rect = lastRect.current
  const left = rect ? Math.min(rect.right + GAP, window.innerWidth - CARD_W - EDGE) : 0
  const top = rect ? Math.max(EDGE, Math.min(rect.top + rect.height / 2 - CARD_H / 2, window.innerHeight - CARD_H - EDGE)) : 0

  return (
    <div className={`pose-preview ${visible ? 'show' : ''}`} style={{ left, top }} aria-hidden={!visible}>
      <div className="pose-preview-robot">
        <RobotViewer embedded look="stage" fov={PREVIEW_FOV} pose={shown && hover && shown.pose === hover.pose ? shown.links : null} />
      </div>
      {move && <p>{move.label}</p>}
    </div>
  )
}
