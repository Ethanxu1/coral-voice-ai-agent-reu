import { useState } from 'react'
import { getRobotStream } from '../demo/robotConfig'

export function LiveStream({
  className = '',
  style,
  badge = true,
}: {
  className?: string
  style?: React.CSSProperties
  badge?: boolean
}) {
  const [key, setKey] = useState(0)
  // Preserve the camera's native aspect ratio so the full field of view is
  // visible instead of being cropped to a hard-coded container shape.
  const [aspectRatio, setAspectRatio] = useState<number | null>(null)

  const containerStyle: React.CSSProperties = {
    ...style,
    aspectRatio: aspectRatio ? `${aspectRatio}` : undefined,
    // When the parent forces a different shape, show the full frame with
    // letterboxing rather than cropping the child out of view.
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  }

  return (
    <div className={`tui-stream ${className}`} style={containerStyle}>
      <img
        key={key}
        src={`${getRobotStream()}/video_feed`}
        alt="Live camera"
        onLoad={(e) => setAspectRatio(e.currentTarget.naturalWidth / e.currentTarget.naturalHeight)}
        onError={() => setTimeout(() => setKey((k) => k + 1), 2000)}
        style={{ width: '100%', height: '100%', objectFit: 'contain', display: 'block' }}
      />
      {badge && <span className="tui-live-badge">● LIVE</span>}
    </div>
  )
}
