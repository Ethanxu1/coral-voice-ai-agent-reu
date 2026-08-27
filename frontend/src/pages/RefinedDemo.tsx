import { useCallback, useEffect, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  useRefinedDemoMachine,
  type RefinedChatMsg,
} from '../demo/useRefinedDemoMachine'
import { resetPose } from '../demo/api'
import { useHardwareDispatching } from '../demo/hardwareDispatchStatus'
import { LiveStream } from './DummyStream'
import RobotViewer from './RobotViewer'
import StreamSourceToggle from '../components/StreamSourceToggle'
import './RefinedDemo.css'

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
    toggleApprovals,
    goToLibrary,
    goToExit,
    startAgain,
    toggleMute,
    skipSubjectSelect,
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
  // Fires whenever a pose save or demonstrate dispatch is targeting hardware —
  // shown in sim mode too (no robot attached) so it's usable for debugging;
  // see the 2026-08-27 fix.
  const hardwareDispatching = useHardwareDispatching()

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
          <StreamSourceToggle compact />
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
          <button
            className={`rd-topbar-btn ${state.approvalsEnabled ? 'ghost' : 'muted active'}`}
            onClick={toggleApprovals}
            title={
              state.approvalsEnabled
                ? 'Turn intent approval pop-ups off (auto-approve)'
                : 'Turn intent approval pop-ups on'
            }
          >
            {state.approvalsEnabled ? 'Approvals: On' : 'Approvals: Off'}
          </button>
          {isActive && (
            <button
              className={`rd-topbar-btn ${state.muted ? 'muted active' : 'ghost'}`}
              onClick={toggleMute}
              title={state.muted ? 'Unmute microphone' : 'Mute microphone'}
            >
              {state.muted ? (
                <>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M19 11h-1.7c0 .74-.16 1.43-.43 2.05l1.23 1.23c.56-.98.9-2.09.9-3.28zm-4.02.17c0-.06.02-.11.02-.17V5c0-1.66-1.34-3-3-3S9 3.34 9 5v.18l5.98 5.99zM4.27 3L3 4.27l6.01 6.01V11c0 1.66 1.33 3 2.99 3 .22 0 .44-.03.65-.08l1.66 1.66c-.71.33-1.5.52-2.31.52-2.76 0-5.3-2.1-5.3-5.1H5c0 3.41 2.72 6.23 6 6.72V21h2v-3.28c.91-.13 1.77-.45 2.54-.9L19.73 21 21 19.73 4.27 3z" />
                  </svg>
                  Muted
                </>
              ) : (
                <>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z" />
                    <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z" />
                  </svg>
                  Mute
                </>
              )}
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

          {hardwareDispatching && (
            <div className="rd-hardware-badge">
              <span className="rd-hardware-badge-dot" />
              Executing on robot…
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

      {/* Subject-select modal — locks the demo to one person at session start */}
      {state.stage === 'SUBJECT_SELECT' && (
        <div className="rd-subject-modal">
          <div className="rd-subject-header">
            <div className="rd-subject-tag">STEP 1 · WHO AM I FOLLOWING?</div>
            <h2 className="rd-subject-title">Raise one hand for 3 seconds</h2>
            <div className="rd-subject-subtitle">
              I'll lock on to you so I don't get confused if other people walk by.
            </div>
          </div>
          <div className="rd-subject-camera">
            <LiveStream badge={false} />
            <div className="rd-subject-camera-live">
              <span className="rd-subject-camera-live-dot" />
              <span>LIVE</span>
            </div>
          </div>
          <div className="rd-subject-status-row">
            <span
              className={`rd-subject-status-dot ${state.selectionState}`}
              aria-hidden
            />
            <span className="rd-subject-status-text">
              {state.selectionState === 'selected'
                ? 'Got you!'
                : state.selectionSubjectsCount === 0
                ? 'Waiting for someone to appear in the frame…'
                : state.selectionHoldProgress > 0
                ? `Hold it there… ${Math.round(state.selectionHoldProgress * 100)}%`
                : `Raise a hand above your head (${state.selectionSubjectsCount} ${
                    state.selectionSubjectsCount === 1 ? 'person' : 'people'
                  } in view)`}
            </span>
          </div>
          <div className="rd-subject-progress">
            <div
              className="rd-subject-progress-fill"
              style={{ width: `${Math.min(100, state.selectionHoldProgress * 100)}%` }}
            />
          </div>
          <button className="rd-subject-skip" onClick={skipSubjectSelect}>
            Skip — continue without locking on
          </button>
        </div>
      )}

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
                  {hardwareDispatching && (
                    <div className="rd-hardware-badge">
                      <span className="rd-hardware-badge-dot" />
                      Executing on robot…
                    </div>
                  )}
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
  orbState: 'listening' | 'thinking' | 'countdown' | 'muted'
  statusText: string
  micLevel: number
}) {
  return (
    <div className="rd-orb-section">
      <div className="rd-orb-wrap">
        <div className={`rd-orb ${orbState}`}>
          <div className="rd-orb-inner" />
        </div>
        {(orbState === 'listening' || orbState === 'muted') && micLevel > 5 && (
          <div className="rd-mic-ring" />
        )}
      </div>
      <div className="rd-status-text">{statusText}</div>
      {(orbState === 'listening' || orbState === 'muted') && (
        <div className="rd-mic-level">
          <div
            className={`rd-mic-level-fill ${orbState === 'muted' ? 'muted' : ''}`}
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

function intentLabel(type: string | undefined): string {
  switch (type) {
    case 'motion': return 'motion'
    case 'conversation': return 'conversation'
    case 'clarification': return 'clarification'
    case 'immediate': return 'system command'
    default: return type ?? 'unknown'
  }
}

function classifierLabel(c: 'regex' | 'llm' | undefined): string {
  return c === 'regex' ? 'regex' : c === 'llm' ? 'LLM' : ''
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
      {msg.role === 'child' && msg.intentType && (
        <div
          className="rd-intent-meta"
          title={msg.intentReason || 'Intent classification metadata'}
        >
          <span className={`rd-intent-badge rd-intent-type-${msg.intentType}`}>
            {intentLabel(msg.intentType)}
          </span>
          <span className={`rd-intent-badge rd-intent-classifier-${msg.intentClassifier}`}>
            {classifierLabel(msg.intentClassifier)}
          </span>
        </div>
      )}
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
