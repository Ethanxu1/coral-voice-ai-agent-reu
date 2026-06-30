import { HumanoidTPose } from './Characters'

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
