import { useState } from 'react'
import { useRobotConfig, getRobotStream } from '../demo/robotConfig'
import { HumanoidTPose } from './Characters'

/** Live MJPEG feed from the vision server (Mac webcam) or the Pi's camera stream,
 * depending on the sim/hardware toggle — styled like tui-stream. Auto-retries if
 * the stream drops (e.g. vision server still warming up). */
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
  useRobotConfig() // re-render so `src` picks up a sim/hardware mode change
  return (
    <div className={`tui-stream ${className}`} style={style}>
      <img
        key={key}
        src={`${getRobotStream()}/video_feed`}
        alt="Live camera"
        onError={() => setTimeout(() => setKey((k) => k + 1), 2000)}
        style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block', transform: 'scaleX(-1)' }}
      />
      {badge && <span className="tui-live-badge">● LIVE</span>}
    </div>
  )
}

interface DummyStreamProps {
  className?: string
  style?: React.CSSProperties
  showPerson?: boolean
  personWidth?: number
}

export function DummyStream({
  className = '',
  style,
  showPerson = true,
  personWidth = 140,
}: DummyStreamProps) {
  return (
    <div className={`tui-stream ${className}`} style={style}>
      <div className="tui-stream-bg" />
      {showPerson && (
        <div className="tui-stream-silhouette">
          <HumanoidTPose width={personWidth} />
        </div>
      )}
      <span className="tui-live-badge">● LIVE</span>
    </div>
  )
}

/* Captured (frozen) frame — simulates classified photo */
export function DummyFrame({
  className = '',
  style,
}: {
  className?: string
  style?: React.CSSProperties
}) {
  return (
    <div
      className={className}
      style={{
        position: 'relative',
        overflow: 'hidden',
        background: 'linear-gradient(180deg, #87CEEB 55%, #90EE90 55%)',
        ...style,
      }}
    >
      {/* ground shadow */}
      <div
        style={{
          position: 'absolute',
          bottom: '28%',
          left: '50%',
          transform: 'translateX(-50%)',
          width: '120px',
          height: '18px',
          borderRadius: '50%',
          background: 'rgba(0,0,0,0.15)',
        }}
      />
      <div
        style={{
          position: 'absolute',
          bottom: '28%',
          left: '50%',
          transform: 'translateX(-50%)',
        }}
      >
        <HumanoidTPose width={180} />
      </div>
    </div>
  )
}
