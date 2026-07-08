import { useCallback, useEffect, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  useRefinedDemoMachine,
  type RefinedChatMsg,
} from '../demo/useRefinedDemoMachine'
import { LiveStream } from './DummyStream'
import './RefinedDemo.css'

export default function RefinedDemo() {
  const location = useLocation()
  const navigate = useNavigate()
  const { state, start, stop, injectText, goToLibrary, goToExit, startAgain } =
    useRefinedDemoMachine()

  const handleExit = useCallback(() => {
    stop()
    navigate('/')
  }, [stop, navigate])

  useEffect(() => {
    if (!(location.state as { fromApp?: boolean } | null)?.fromApp) {
      navigate('/', { replace: true })
      return
    }
    start()
    return () => {
      stop()
    }
  }, [])

  const isActive = !['IDLE', 'ERROR'].includes(state.stage)

  return (
    <div className="rd-root">
      {/* Top bar */}
      <header className="rd-topbar">
        <div className="rd-topbar-left">
          <div className="rd-logo">
            coral<span>.</span>
          </div>
        </div>
        <div className="rd-topbar-right">
          {isActive && (
            <button
              className="rd-topbar-btn ghost"
              onClick={goToLibrary}
            >
              My Poses{state.savedPoses.length > 0 ? ` · ${state.savedPoses.length}` : ''}
            </button>
          )}
          {isActive && (
            <button className="rd-topbar-btn danger" onClick={goToExit}>
              Exit
            </button>
          )}
        </div>
      </header>

      {/* Main */}
      <main className="rd-main">
        {/* Camera panel */}
        <div className="rd-camera-panel">
          <LiveStream badge={false} />

          {/* Dynamic live/freeze badge */}
          {(() => {
            const isFrozen = !!state.capturedFrame && state.stage !== 'LISTENING' && state.stage !== 'FOLLOWING'
            return isFrozen
              ? <span className="tui-live-badge rd-freeze-badge">■ FREEZE</span>
              : <span className="tui-live-badge">● LIVE</span>
          })()}

          {state.followActive && (
            <div className="rd-follow-badge">
              <span className="rd-follow-dot" />
              Following
            </div>
          )}

          {state.capturedFrame && state.stage !== 'LISTENING' && state.stage !== 'FOLLOWING' && (
            <img
              className="rd-captured-img"
              src={`data:image/jpeg;base64,${state.capturedFrame}`}
              alt="Captured pose"
            />
          )}

          {state.stage === 'CAPTURED' && (
            <div className="rd-captured-badge">Pose captured!</div>
          )}

          {state.flash && <div className="rd-flash" />}

          {state.stage === 'NAMING' && (
            <div className="rd-naming-overlay">
              <div className="rd-naming-card">
                <div className="rd-naming-tag">NAMING YOUR POSE</div>
                <div className="rd-naming-title">What should we call it?</div>
                <div className="rd-naming-hint">
                  <span className="rd-naming-dot" />
                  Just say a name out loud
                </div>
              </div>
            </div>
          )}

          {state.stage === 'IDLE' && (
            <div className="rd-idle-overlay">
              <div className="rd-idle-title">Ready to move?</div>
              <button className="rd-start-btn" onClick={startAgain}>
                Start Session
              </button>
            </div>
          )}
        </div>

        {/* Right panel */}
        <div className="rd-right-panel">
          {/* Orb + status */}
          <OrbSection
            orbState={state.orbState}
            statusText={state.statusText}
            micLevel={state.micLevel}
          />

          {/* Chat messages */}
          <ChatArea messages={state.messages} onChip={injectText} />

          {/* Library bar when in LIBRARY stage */}
          {state.stage === 'LIBRARY' && (
            <div className="rd-library-bar">
              <div className="rd-library-title">Saved Poses</div>
              {state.savedPoses.length > 0 ? (
                <div className="rd-pose-chips">
                  {state.savedPoses.map((name) => (
                    <button
                      key={name}
                      className="rd-pose-chip"
                      onClick={() => injectText(name)}
                    >
                      {name}
                    </button>
                  ))}
                </div>
              ) : (
                <div className="rd-pose-empty">No poses saved yet.</div>
              )}
            </div>
          )}
        </div>
      </main>

      {/* Countdown modal */}
      {state.stage === 'COUNTDOWN' && state.countdown != null && (
        <div className="rd-countdown-modal">
          <div className="rd-countdown-card">
            <div className="rd-countdown-label">Get ready!</div>
            <span key={state.countdown} className="rd-countdown-num">
              {state.countdown}
            </span>
          </div>
        </div>
      )}

      {/* Exit confirm overlay */}
      {state.stage === 'EXIT_CONFIRM' && (
        <div className="rd-overlay">
          <div className="rd-overlay-card">
            <div className="rd-overlay-title">Great session!</div>
            <div className="rd-overlay-subtitle">
              {state.savedPoses.length > 0
                ? `You saved ${state.savedPoses.length} pose${state.savedPoses.length !== 1 ? 's' : ''} today.`
                : "You didn't save any poses — come back and try again!"}
            </div>
            {state.savedPoses.length > 0 && (
              <div className="rd-exit-poses">
                {state.savedPoses.map((name) => (
                  <span key={name} className="rd-exit-pose-tag">
                    {name}
                  </span>
                ))}
              </div>
            )}
            <div className="rd-overlay-btns">
              <button
                className="rd-overlay-btn primary"
                onClick={startAgain}
              >
                Make more poses!
              </button>
              <button className="rd-overlay-btn secondary" onClick={handleExit}>
                All done
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Error overlay */}
      {state.stage === 'ERROR' && (
        <div className="rd-overlay">
          <div className="rd-overlay-card">
            <div className="rd-overlay-title">Something went wrong</div>
            <div className="rd-overlay-subtitle">
              {state.error || 'An unexpected error occurred.'}
            </div>
            <div className="rd-overlay-btns">
              <button className="rd-overlay-btn primary" onClick={startAgain}>
                Try again
              </button>
              <button className="rd-overlay-btn secondary" onClick={handleExit}>
                Exit
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

/* ── Orb section ─────────────────────────────────────────────────────────────── */
function OrbSection({
  orbState,
  statusText,
  micLevel,
}: {
  orbState: 'listening' | 'thinking' | 'countdown'
  statusText: string
  micLevel: number
}) {
  return (
    <div className="rd-orb-section">
      <div className="rd-orb-wrap">
        <div className={`rd-orb ${orbState}`}>
          <div className="rd-orb-inner" />
        </div>
        {orbState === 'listening' && micLevel > 5 && (
          <div className="rd-mic-ring" />
        )}
      </div>
      <div className="rd-status-text">{statusText}</div>
      {orbState === 'listening' && (
        <div className="rd-mic-level">
          <div
            className="rd-mic-level-fill"
            style={{ width: `${Math.min(100, (micLevel / 40) * 100)}%` }}
          />
        </div>
      )}
    </div>
  )
}

/* ── Chat area ───────────────────────────────────────────────────────────────── */
function ChatArea({
  messages,
  onChip,
}: {
  messages: RefinedChatMsg[]
  onChip: (text: string) => void
}) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  return (
    <div className="rd-chat-area">
      {messages.map((msg, i) => (
        <ChatMsg key={i} msg={msg} onChip={onChip} />
      ))}
      <div ref={bottomRef} />
    </div>
  )
}

function ChatMsg({
  msg,
  onChip,
}: {
  msg: RefinedChatMsg
  onChip: (text: string) => void
}) {
  return (
    <div className={`rd-msg ${msg.role}`}>
      <div className="rd-bubble">{msg.text}</div>
      {msg.chips && msg.chips.length > 0 && (
        <div className="rd-chips">
          {msg.chips.map((chip) => (
            <button key={chip} className="rd-chip" onClick={() => onChip(chip)}>
              {chip}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
