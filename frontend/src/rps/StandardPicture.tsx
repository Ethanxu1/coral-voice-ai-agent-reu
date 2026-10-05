import { useState } from 'react'
import GestureFigure from './GestureFigure'
import type { GestureDef } from './gestures'

/**
 * Still picture of the standard move. Uses /rps/<id>.png from frontend/public if
 * one has been added (e.g. a real screenshot), otherwise draws the stick figure.
 */
export default function StandardPicture({ gesture }: { gesture: GestureDef }) {
  const [missing, setMissing] = useState(false)
  if (missing) {
    return (
      <div className="rps-standard-figure">
        <GestureFigure gesture={gesture} />
      </div>
    )
  }
  return (
    <img
      className="rps-standard-img"
      src={`/rps/${gesture.id}.png`}
      alt={`Standard ${gesture.label}`}
      onError={() => setMissing(true)}
    />
  )
}
