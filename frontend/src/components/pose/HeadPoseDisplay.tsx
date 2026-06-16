import type { HeadPose } from '../../types/pose'

interface GaugeProps {
  label: string
  value: number
  color: string
}

function Gauge({ label, value, color }: GaugeProps) {
  const clamped = Math.max(-90, Math.min(90, value))
  const pct = ((clamped + 90) / 180) * 100
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, fontSize: 12 }}>
        <span style={{ color: '#aaa' }}>{label}</span>
        <span style={{ color, fontFamily: 'monospace', fontWeight: 'bold' }}>
          {value.toFixed(1)}°
        </span>
      </div>
      <div style={{ height: 8, background: '#333', borderRadius: 4, position: 'relative' }}>
        {/* Zero marker */}
        <div style={{
          position: 'absolute', left: '50%', top: 0, bottom: 0,
          width: 1, background: '#666', transform: 'translateX(-50%)'
        }} />
        {/* Value indicator */}
        <div style={{
          position: 'absolute', left: `${pct}%`, top: -2, bottom: -2,
          width: 4, background: color, borderRadius: 2,
          transform: 'translateX(-50%)', transition: 'left 0.05s'
        }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, color: '#555', marginTop: 2 }}>
        <span>-90°</span><span>0°</span><span>+90°</span>
      </div>
    </div>
  )
}

interface Props {
  headPose: HeadPose | null
}

export default function HeadPoseDisplay({ headPose }: Props) {
  const yaw = headPose?.yaw ?? 0
  const pitch = headPose?.pitch ?? 0
  const roll = headPose?.roll ?? 0

  return (
    <div style={{ padding: '12px 16px', background: '#1a1a1a', borderRadius: 8 }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: '#ddd', marginBottom: 12 }}>
        Head Orientation
      </div>
      <Gauge label="Yaw (left/right)" value={yaw} color="#ff4444" />
      <Gauge label="Pitch (up/down)" value={pitch} color="#44ff44" />
      <Gauge label="Roll (tilt)" value={roll} color="#4488ff" />
      {!headPose && (
        <div style={{ color: '#666', fontSize: 11, textAlign: 'center', marginTop: 4 }}>
          No head detected
        </div>
      )}
    </div>
  )
}
