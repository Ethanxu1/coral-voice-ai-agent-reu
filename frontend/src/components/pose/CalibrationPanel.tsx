import type { CalibrationStatus } from '../../types/pose'

interface Props {
  status: CalibrationStatus
  isConnected: boolean
  onStart: () => void
  onReset: () => void
}

const STATE_COLORS: Record<string, string> = {
  idle: '#888',
  collecting: '#f90',
  calibrated: '#0f0',
}

const STATE_LABELS: Record<string, string> = {
  idle: 'Not calibrated',
  collecting: 'Collecting...',
  calibrated: 'Calibrated',
}

export default function CalibrationPanel({ status, isConnected, onStart, onReset }: Props) {
  const color = STATE_COLORS[status.state] ?? '#888'
  const pct = Math.round(status.progress * 100)

  return (
    <div style={{ padding: '12px 16px', background: '#1a1a1a', borderRadius: 8, marginBottom: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: '#ddd' }}>Calibration</span>
        <span style={{ fontSize: 12, color, fontWeight: 600 }}>
          {STATE_LABELS[status.state]}
        </span>
      </div>

      {status.state === 'collecting' && (
        <div style={{ marginBottom: 10 }}>
          <div style={{ height: 6, background: '#333', borderRadius: 3, overflow: 'hidden' }}>
            <div style={{ height: '100%', width: `${pct}%`, background: '#f90', transition: 'width 0.1s' }} />
          </div>
          <div style={{ fontSize: 11, color: '#888', marginTop: 4 }}>
            Collecting frames... {status.frame_count}/60
          </div>
        </div>
      )}

      {status.state === 'idle' && (
        <div style={{ fontSize: 11, color: '#666', marginBottom: 10 }}>
          Stand facing the camera in a neutral position, then click Start.
        </div>
      )}

      <div style={{ display: 'flex', gap: 8 }}>
        <button
          onClick={onStart}
          disabled={!isConnected || status.state !== 'idle'}
          style={{
            flex: 1, padding: '6px 12px', borderRadius: 6, border: 'none',
            background: (!isConnected || status.state !== 'idle') ? '#333' : '#2563eb',
            color: (!isConnected || status.state !== 'idle') ? '#666' : '#fff',
            cursor: (!isConnected || status.state !== 'idle') ? 'default' : 'pointer',
            fontSize: 12, fontWeight: 600,
          }}
        >
          Start Calibration
        </button>
        <button
          onClick={onReset}
          disabled={!isConnected || status.state === 'idle'}
          style={{
            padding: '6px 12px', borderRadius: 6, border: 'none',
            background: (!isConnected || status.state === 'idle') ? '#333' : '#444',
            color: (!isConnected || status.state === 'idle') ? '#555' : '#bbb',
            cursor: (!isConnected || status.state === 'idle') ? 'default' : 'pointer',
            fontSize: 12,
          }}
        >
          Reset
        </button>
      </div>
    </div>
  )
}
