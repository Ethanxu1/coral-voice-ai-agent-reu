import { LiveStream } from './DummyStream'
import type { PageProps } from './TestUIRouter'

export default function Page3_ClassifyCountdown({ state }: PageProps) {
  return (
    <div className="tui-page p3-layout">
      <LiveStream className="p3-stream-full" />

      {/* camera flash on shutter */}
      {state.flash && <div className="p3-flash" />}

      {/* real 3-2-1 driven by the state machine */}
      {state.countdown != null && (
        <div className="p3-countdown-overlay">
          <div key={state.countdown} className="p3-number">{state.countdown}</div>
        </div>
      )}

      {/* subtle top hint */}
      <div
        style={{
          position: 'absolute',
          top: 14,
          left: '50%',
          transform: 'translateX(-50%)',
          background: 'rgba(255,255,255,0.7)',
          backdropFilter: 'blur(6px)',
          borderRadius: 999,
          padding: '5px 18px',
          fontWeight: 800,
          fontSize: 14,
          color: '#6a5acd',
          whiteSpace: 'nowrap',
          zIndex: 6,
        }}
      >
        {state.classifying ? '📸 Snap!' : 'Hold your pose! 📸'}
      </div>
    </div>
  )
}
