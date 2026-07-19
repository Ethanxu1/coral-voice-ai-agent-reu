import { useCallback, useEffect, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  useRefinedDemoMachine,
  type RefinedChatMsg,
} from '../demo/useRefinedDemoMachine'
import { resetPose } from '../demo/api'
import { LiveStream } from './DummyStream'
import RobotViewer from './RobotViewer'
import './RefinedDemo.css'


function RobotIllustration() {
  return (
    <div className="rd-robot">
      <div className="rd-robot-neck-wrap">
        <div className="rd-robot-antenna" />
        <div className="rd-robot-neck" />
      </div>
      <div className="rd-robot-head">
        <div className="rd-robot-eye" />
        <div className="rd-robot-eye" />
      </div>
      <div className="rd-robot-torso-wrap">
        <div className="rd-robot-torso">
          <div className="rd-robot-chest">
            <div className="rd-robot-bar" style={{ width: 6, height: 14 }} />
            <div className="rd-robot-bar" style={{ width: 6, height: 26 }} />
            <div className="rd-robot-bar" style={{ width: 6, height: 18 }} />
            <div className="rd-robot-bar" style={{ width: 6, height: 10 }} />
          </div>
        </div>
        <div className="rd-robot-arm rd-robot-arm-left">
          <div className="rd-robot-joint" />
          <div className="rd-robot-limb" />
        </div>
        <div className="rd-robot-arm rd-robot-arm-right">
          <div className="rd-robot-joint" />
          <div className="rd-robot-limb" />
        </div>
      </div>
      <div className="rd-robot-legs">
        <div className="rd-robot-leg" />
        <div className="rd-robot-leg" />
      </div>
    </div>
  )
}

export default function RefinedDemo() {
  const location = useLocation()
  const navigate = useNavigate()
  const {
    state,
    start,
    stop,
    injectText,
    approveIntent,
    rejectIntent,
    goToLibrary,
    goToExit,
    startAgain,
  } = useRefinedDemoMachine()

  const handleExit = useCallback(() => {
    stop()
    navigate('/')
  }, [stop, navigate])

  useEffect(() => {
    if (!(location.state as { fromApp?: boolean } | null)?.fromApp) {
      navigate('/welcome', { replace: true })
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
          <button
            className="rd-topbar-btn ghost"
            onClick={() => { resetPose().catch(() => {}) }}
          >
            Return to stand
          </button>
          <button
            className="rd-topbar-btn ghost"
            onClick={() => navigate('/tutorial')}
          >
            Tutorial
          </button>
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
              End Session
            </button>
          )}
        </div>
      </header>

      {/* Main */}
      <main className="rd-main">
        {/* Camera panel */}
        <div className="rd-camera-panel">
          <div className="rd-sim-grid" />
          <div className="rd-sim-vignette" />
          <div className="rd-sim-badge"><span className="rd-sim-badge-dot" />SIM</div>
          <div className="rd-sim-safety"><span className="rd-sim-safety-dot" />Safe zone</div>
          <RobotViewer embedded />
          <div className="rd-pip">
            <LiveStream badge={false} />
            <div className="rd-pip-live">
              <span className="rd-pip-live-dot" />
              <span className="rd-pip-live-text">LIVE</span>
            </div>
          </div>

          {state.followActive && (
            <div className="rd-follow-badge">
              <span className="rd-follow-dot" />
              Following
            </div>
          )}

          {state.stage === 'CAPTURED' && !state.safetyChecking && (
            <div className="rd-captured-badge">Pose captured!</div>
          )}

          {state.safetyChecking && (
            <div className="rd-safety-badge">
              <span className="rd-safety-spinner" />
              Safety check…
            </div>
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

          {/* Captured pose thumbnail */}
          {state.capturedFrame && state.stage !== 'LISTENING' && state.stage !== 'FOLLOWING' && (
            <div className="rd-capture-stage">
              <img
                className="rd-capture-frame"
                src={`data:image/jpeg;base64,${state.capturedFrame}`}
                alt="Captured pose"
              />
            </div>
          )}

          {/* Chat messages */}
          <ChatArea
            messages={state.messages}
            onChip={injectText}
            agentTyping={state.orbState === 'thinking'}
          />

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
            <div className="rd-overlay-title">
              {state.savedPoses.length > 0 ? 'Here are the moves you taught me!' : 'End Session'}
            </div>
            <div className="rd-overlay-blurb">
              You might be wondering how I knew which move to do. I have a special
              machine that tells me where your arms and legs are in the picture,
              and then I use that to make my arms and legs match that pose!
            </div>

            {state.savedPoses.length > 0 && (
              <>
                {/* Live sim so the child sees the robot strike each saved move. */}
                <div className="rd-exit-stage">
                  <RobotViewer embedded />
                  <div className="rd-exit-stage-caption">
                    {state.replayIdx !== null
                      ? `Performing "${state.savedPoses[state.replayIdx]}" · ${state.replayIdx + 1} of ${state.savedPoses.length}`
                      : "That's every move you taught me!"}
                  </div>
                </div>
                <div className="rd-exit-poses">
                  {state.savedPoses.map((name, i) => (
                    <span
                      key={name}
                      className={`rd-exit-pose-tag${i === state.replayIdx ? ' rd-exit-pose-tag-active' : ''}`}
                    >
                      {name}
                    </span>
                  ))}
                </div>
              </>
            )}

            <div className="rd-overlay-subtitle">
              {state.savedPoses.length > 0
                ? `You saved ${state.savedPoses.length} pose${state.savedPoses.length !== 1 ? 's' : ''} today.`
                : "You didn't save any poses — come back and try again!"}
            </div>
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

      {/* Intent approval modal — placeholder gate before executing a branch. */}
      {state.pendingIntent && (
        <div className="rd-overlay">
          <div className="rd-overlay-card">
            <div className="rd-overlay-title">Is this right?</div>
            <div className="rd-intent-label">What I'll do</div>
            <div className="rd-intent-pill">{state.pendingIntent}</div>
            <div className="rd-overlay-btns">
              <button className="rd-overlay-btn primary" onClick={approveIntent}>
                Approve
              </button>
              <button className="rd-overlay-btn secondary" onClick={rejectIntent}>
                Reject
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
  agentTyping,
}: {
  messages: RefinedChatMsg[]
  onChip: (text: string) => void
  agentTyping: boolean
}) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, agentTyping])

  return (
    <div className="rd-chat-area">
      {messages.map((msg, i) => (
        <ChatMsg key={i} msg={msg} onChip={onChip} />
      ))}
      {agentTyping && <TypingIndicator />}
      <div ref={bottomRef} />
    </div>
  )
}

function TypingIndicator() {
  return (
    <div className="rd-msg agent">
      <div className="rd-bubble rd-typing" aria-label="Agent is typing">
        <span className="rd-typing-dot" />
        <span className="rd-typing-dot" />
        <span className="rd-typing-dot" />
      </div>
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
      <div className="rd-bubble">
        {msg.text}
        {msg.role === 'child' && msg.audioUrl && (
          <button
            className="rd-audio-play-btn"
            onClick={() => new Audio(msg.audioUrl).play()}
            title="Play recording"
            aria-label="Play recording"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
              <polygon points="2,1 12,7 2,13" />
            </svg>
          </button>
        )}
      </div>
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
