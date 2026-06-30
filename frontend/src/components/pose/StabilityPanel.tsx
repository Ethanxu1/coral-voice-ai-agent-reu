import type { StabilityStatus } from '../../types/pose'

interface Props {
  status: StabilityStatus
  isConnected: boolean
  onCapture: () => void
  onContinue: () => void
}

const STATE_COLORS: Record<string, string> = {
  idle: '#888',
  countdown: '#0cf',
  collecting: '#f90',
  frozen: '#0f0',
}

const STATE_LABELS: Record<string, string> = {
  idle: 'Ready',
  countdown: 'Get ready...',
  collecting: 'Analyzing...',
  frozen: 'Captured',
}

export default function StabilityPanel({ status, isConnected, onCapture, onContinue }: Props) {
  const color = STATE_COLORS[status.state] ?? '#888'
  const collectPct = Math.round(status.collection_progress * 100)
  const countdownDigit = Math.max(1, Math.ceil(status.countdown_remaining))

  const captureDisabled = !isConnected || status.state !== 'idle'
  const continueDisabled = !isConnected || status.state !== 'frozen'

  return (
    <div style={{ padding: '12px 16px', background: '#1a1a1a', borderRadius: 8, marginBottom: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: '#ddd' }}>Stable Position</span>
        <span style={{ fontSize: 12, color, fontWeight: 600 }}>
          {STATE_LABELS[status.state]}
        </span>
      </div>

      {status.state === 'countdown' && (
        <div style={{ marginBottom: 10, textAlign: 'center' }}>
          <div style={{ fontSize: 42, fontWeight: 700, color: '#0cf', lineHeight: 1 }}>
            {countdownDigit}
          </div>
          <div style={{ fontSize: 11, color: '#888', marginTop: 4 }}>
            Hold your position...
          </div>
        </div>
      )}

      {status.state === 'collecting' && (
        <div style={{ marginBottom: 10 }}>
          <div style={{ height: 6, background: '#333', borderRadius: 3, overflow: 'hidden' }}>
            <div style={{ height: '100%', width: `${collectPct}%`, background: '#f90', transition: 'width 0.1s' }} />
          </div>
          <div style={{ fontSize: 11, color: '#888', marginTop: 4 }}>
            Finding most stable frame... {collectPct}%
          </div>
        </div>
      )}

      {status.state === 'idle' && (
        <div style={{ fontSize: 11, color: '#666', marginBottom: 10 }}>
          Click to capture a snapshot of your most stable pose over a short window.
        </div>
      )}

      {status.state === 'frozen' && (
        <div style={{ fontSize: 11, color: '#0a0', marginBottom: 10 }}>
          Stable frame locked. Camera and 3D skeleton are paused.
        </div>
      )}

      {status.state === 'frozen' ? (
        <button
          onClick={onContinue}
          disabled={continueDisabled}
          style={{
            width: '100%', padding: '6px 12px', borderRadius: 6, border: 'none',
            background: continueDisabled ? '#333' : '#16a34a',
            color: continueDisabled ? '#666' : '#fff',
            cursor: continueDisabled ? 'default' : 'pointer',
            fontSize: 12, fontWeight: 600,
          }}
        >
          Continue
        </button>
      ) : (
        <button
          onClick={onCapture}
          disabled={captureDisabled}
          style={{
            width: '100%', padding: '6px 12px', borderRadius: 6, border: 'none',
            background: captureDisabled ? '#333' : '#2563eb',
            color: captureDisabled ? '#666' : '#fff',
            cursor: captureDisabled ? 'default' : 'pointer',
            fontSize: 12, fontWeight: 600,
          }}
        >
          Capture Stable Position
        </button>
      )}
    </div>
  )
}
