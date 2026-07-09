import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useProDemoMachine, type ProState, type ProStatus } from '../demo/useProDemoMachine'
import { LiveStream } from './DummyStream'
import './ProDemo.css'

const PHASES: { key: ProState['stage'][]; label: string }[] = [
  { key: ['WATCH'], label: 'Capture' },
  { key: ['COUNTDOWN', 'LOADING'], label: 'Retarget' },
  { key: ['ADJUST'], label: 'Adjust' },
  { key: ['NAME'], label: 'Name' },
]

export default function ProDemo() {
  const { state, start, retry, exit, toggleInputMode, submitText, skip } = useProDemoMachine()
  const running = !['IDLE', 'DONE', 'ERROR'].includes(state.stage)

  return (
    <div className="pro-root">
      <header className="pro-topbar">
        <div className="pro-topbar-left">
          <Link to="/" className="pro-back">← Back</Link>
          <span className="pro-title">Coral · Motion Retargeting</span>
        </div>
        <div className="pro-topbar-center">
          {running && (
            <div className="pro-rounds">
              {Array.from({ length: state.totalLoops }).map((_, i) => (
                <span
                  key={i}
                  className={`pro-round-dot ${i < state.loop ? 'done' : ''} ${i === state.loop ? 'active' : ''}`}
                />
              ))}
              <span className="pro-round-label">
                Round {Math.min(state.loop + 1, state.totalLoops)} / {state.totalLoops}
              </span>
            </div>
          )}
        </div>
        <div className="pro-topbar-right">
          <button className="pro-btn ghost" onClick={toggleInputMode}>
            {state.inputMode === 'voice' ? '🎤 Voice' : '⌨️ Text'}
          </button>
          {running && <button className="pro-btn" onClick={exit}>End</button>}
        </div>
      </header>

      {running && <PhaseBar stage={state.stage} />}

      <main className="pro-stage">
        <Stage state={state} onSubmitText={submitText} onSkip={skip} />
        {state.flash && <div className="pro-flash" />}
      </main>

      {state.stage === 'IDLE' && (
        <Overlay
          title="Motion Retargeting Demo"
          message="Three rounds: strike a pose, Coral mirrors it, refine by voice or text, then name it."
          primaryLabel="▶ Start"
          onPrimary={start}
        />
      )}
      {state.stage === 'ERROR' && (
        <Overlay
          title="Something went wrong"
          message={state.error || 'Unexpected error.'}
          primaryLabel="Restart"
          onPrimary={retry}
          onExit={exit}
        />
      )}
    </div>
  )
}

function PhaseBar({ stage }: { stage: ProState['stage'] }) {
  const activeIdx = PHASES.findIndex((p) => p.key.includes(stage))
  return (
    <div className="pro-phasebar">
      {PHASES.map((p, i) => (
        <div key={p.label} className={`pro-phase ${i === activeIdx ? 'active' : ''} ${i < activeIdx ? 'done' : ''}`}>
          <span className="pro-phase-idx">{i + 1}</span>
          <span className="pro-phase-label">{p.label}</span>
        </div>
      ))}
    </div>
  )
}

function Stage({ state, onSubmitText, onSkip }: { state: ProState; onSubmitText: (t: string) => void; onSkip: () => void }) {
  switch (state.stage) {
    case 'DONE':
      return <Results state={state} />
    case 'ADJUST':
    case 'NAME':
      return (
        <div className="pro-split">
          <div className="pro-frame-pane">
            {state.frame ? (
              <img className="pro-frame" src={`data:image/jpeg;base64,${state.frame}`} alt="Captured pose" />
            ) : (
              <div className="pro-frame pro-frame-empty">No frame</div>
            )}
          </div>
          <div className="pro-input-pane">
            <div className="pro-input-title">{state.stage === 'NAME' ? 'Name this move' : 'Refine the pose'}</div>
            <div className="pro-caption-lg">{state.caption}</div>
            {state.awaitingText ? (
              <TextEntry
                placeholder={state.stage === 'NAME' ? 'e.g. Victory Stance' : 'e.g. raise the left arm higher'}
                onSubmit={onSubmitText}
              />
            ) : (
              <StatusPill status={state.status} />
            )}
            {state.stage === 'ADJUST' && (
              <button className="pro-btn ghost pro-skip" onClick={onSkip}>
                Skip adjustment → name it
              </button>
            )}
          </div>
        </div>
      )
    default:
      // WATCH / COUNTDOWN / LOADING — live stream stage
      return (
        <div className="pro-live-wrap">
          <LiveStream className="pro-live" />
          {state.stage === 'LOADING' && (
            <div className="pro-loading">
              <div className="pro-spinner" />
              <div className="pro-loading-label">{state.caption}</div>
            </div>
          )}
          {state.countdown != null && (
            <div className="pro-countdown">
              <span key={state.countdown}>{state.countdown}</span>
            </div>
          )}
          <div className="pro-live-caption">
            {state.stage === 'WATCH' && <span className="pro-pulse-dot" />}
            {state.caption}
          </div>
          {state.detail && <div className="pro-detail">{state.detail}</div>}
        </div>
      )
  }
}

function Results({ state }: { state: ProState }) {
  return (
    <div className="pro-results">
      <div className="pro-results-title">{state.caption || 'Session complete'}</div>
      <div className="pro-results-grid">
        {state.moves.map((m, i) => (
          <div className="pro-move-card" key={i}>
            {m.frame ? (
              <img className="pro-move-img" src={`data:image/jpeg;base64,${m.frame}`} alt={m.name} />
            ) : (
              <div className="pro-move-img pro-frame-empty">No frame</div>
            )}
            <div className="pro-move-meta">
              <span className="pro-move-num">{i + 1}</span>
              <span className="pro-move-name">{m.name}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function StatusPill({ status }: { status: ProStatus }) {
  const map: Record<ProStatus, { icon: string; label: string }> = {
    idle: { icon: '•', label: 'Ready' },
    recording: { icon: '🎤', label: 'Listening…' },
    thinking: { icon: '💭', label: 'Thinking…' },
    action: { icon: '✅', label: 'Applied' },
    clarify: { icon: '🔁', label: 'Try again' },
  }
  const { icon, label } = map[status]
  return (
    <div className={`pro-status pro-status-${status}`}>
      <span className="pro-status-icon">{icon}</span>
      <span>{label}</span>
    </div>
  )
}

function TextEntry({ placeholder, onSubmit }: { placeholder: string; onSubmit: (t: string) => void }) {
  const [value, setValue] = useState('')
  const submit = () => {
    if (value.trim()) onSubmit(value.trim())
  }
  return (
    <div className="pro-text-entry">
      <input
        className="pro-text-input"
        autoFocus
        value={value}
        placeholder={placeholder}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter') submit() }}
      />
      <button className="pro-btn primary" onClick={submit}>Submit</button>
    </div>
  )
}

function Overlay({
  title,
  message,
  primaryLabel,
  onPrimary,
  onExit,
}: {
  title: string
  message: string
  primaryLabel: string
  onPrimary: () => void
  onExit?: () => void
}) {
  return (
    <div className="pro-overlay">
      <div className="pro-overlay-card">
        <div className="pro-overlay-title">{title}</div>
        <div className="pro-overlay-msg">{message}</div>
        <div className="pro-overlay-btns">
          <button className="pro-btn primary" onClick={onPrimary}>{primaryLabel}</button>
          {onExit && <Link to="/"><button className="pro-btn" onClick={onExit}>Exit</button></Link>}
        </div>
      </div>
    </div>
  )
}
