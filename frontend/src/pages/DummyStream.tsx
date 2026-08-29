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
  return (
    <div className={`tui-stream ${className}`} style={style}>
      <img
        key={key}
        src={`${getRobotStream()}/video_feed`}
        alt="Live camera"
        onError={() => setTimeout(() => setKey((k) => k + 1), 2000)}
        style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
      />
      {badge && <span className="tui-live-badge">● LIVE</span>}
    </div>
  )
}
