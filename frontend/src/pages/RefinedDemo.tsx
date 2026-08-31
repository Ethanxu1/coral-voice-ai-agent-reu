import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  useRefinedDemoMachine,
  type RefinedChatMsg,
} from '../demo/useRefinedDemoMachine'
import { fetchIntentExamples, resetPose } from '../demo/api'
import { useHardwareDispatching } from '../demo/hardwareDispatchStatus'
import { useConnectionStatus } from '../components/ConnectionStatus'
import { LiveStream } from './DummyStream'
import RobotViewer from '../components/RobotViewer'
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
    toggleAudioMute,
    skipSubjectSelect,
  } = useRefinedDemoMachine()

  const [showCommands, setShowCommands] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const [examples, setExamples] = useState<{ motion: string[]; immediate: string[]; conversation: string[] }>({
    motion: [],
    immediate: [],
    conversation: [],
  })
  const services = useConnectionStatus()

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

  useEffect(() => {
    if (!showCommands) return
    let cancelled = false
    fetchIntentExamples().then((data) => {
      if (!cancelled) setExamples(data)
    })
    return () => {
      cancelled = true
    }
  }, [showCommands])

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
          <button
            className="rd-topbar-btn ghost"
            onClick={() => { resetPose().catch(() => {}) }}
          >
            Return to stand
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
              className="rd-topbar-btn ghost rd-command-btn"
              onClick={() => setShowCommands(true)}
              title="What can I say?"
              aria-label="Open command help"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 17h-2v-2h2v2zm2.07-7.75l-.9.92C13.45 12.9 13 13.5 13 15h-2v-.5c0-1.1.45-2.1 1.17-2.83l1.24-1.26c.37-.36.59-.86.59-1.41 0-1.1-.9-2-2-2s-2 .9-2 2H8c0-2.21 1.79-4 4-4s4 1.79 4 4c0 .88-.36 1.68-.93 2.25z" />
              </svg>
              What can I say?
            </button>
          )}
          <ConnectionHealthDot services={services} />
          {isActive && (
            <div className="rd-settings-wrap">
              <button
                className="rd-topbar-btn ghost"
                onClick={() => setShowSettings((s) => !s)}
                title="Settings"
                aria-label="Open settings"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58a.49.49 0 0 0 .12-.61l-1.92-3.32a.488.488 0 0 0-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54a.484.484 0 0 0-.48-.41h-3.84a.484.484 0 0 0-.48.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96a.488.488 0 0 0-.59.22L2.74 8.87a.49.49 0 0 0 .12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58a.49.49 0 0 0-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.27.41.48.41h3.84c.24 0 .44-.17.48-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6A3.6 3.6 0 1 1 15.6 12 3.6 3.6 0 0 1 12 15.6z" />
                </svg>
              </button>
              {showSettings && (
                <div className="rd-settings-menu">
                  <label className="rd-settings-row">
                    <span>Intent approvals</span>
                    <button
                      className={`rd-toggle ${state.approvalsEnabled ? 'on' : ''}`}
                      onClick={() => {
                        toggleApprovals()
                        setShowSettings(false)
                      }}
                      aria-label={state.approvalsEnabled ? 'Turn approvals off' : 'Turn approvals on'}
                    >
                      <span className="rd-toggle-knob" />
                    </button>
                  </label>
                </div>
              )}
            </div>
          )}
          {isActive && (
            <button
              className={`rd-topbar-btn ${state.muted ? 'muted active' : 'ghost'}`}
              onClick={toggleMute}
              title={state.muted ? 'Unmute microphone' : 'Mute microphone'}
              aria-label={state.muted ? 'Unmute microphone' : 'Mute microphone'}
            >
              {state.muted ? (
                <>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M19 11h-1.7c0 .74-.16 1.43-.43 2.05l1.23 1.23c.56-.98.9-2.09.9-3.28zm-4.02.17c0-.06.02-.11.02-.17V5c0-1.66-1.34-3-3-3S9 3.34 9 5v.18l5.98 5.99zM4.27 3L3 4.27l6.01 6.01V11c0 1.66 1.33 3 2.99 3 .22 0 .44-.03.65-.08l1.66 1.66c-.71.33-1.5.52-2.31.52-2.76 0-5.3-2.1-5.3-5.1H5c0 3.41 2.72 6.23 6 6.72V21h2v-3.28c.91-.13 1.77-.45 2.54-.9L19.73 21 21 19.73 4.27 3z" />
                  </svg>
                  Muted
                </>
              ) : (
                <>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z" />
                    <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z" />
                  </svg>
                </>
              )}
            </button>
          )}
          {isActive && (
            <button
              className={`rd-topbar-btn ${state.audioMuted ? 'muted active' : 'ghost'}`}
              onClick={toggleAudioMute}
              title={state.audioMuted ? 'Unmute robot voice' : 'Mute robot voice'}
              aria-label={state.audioMuted ? 'Unmute robot voice' : 'Mute robot voice'}
            >
              {state.audioMuted ? (
                <>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M16.5 12c0-1.77-1.02-3.29-2.5-4.03v2.21l2.45 2.45c.03-.2.05-.41.05-.63zm2.5 0c0 .94-.2 1.82-.54 2.64l1.51 1.51C20.63 14.91 21 13.5 21 12c0-4.28-2.99-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM4.27 3L3 4.27 7.73 9H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.18v2.06c1.38-.31 2.63-.95 3.69-1.81L19.73 21 21 19.73l-9-9L4.27 3zM12 4L9.91 6.09 12 8.18V4z" />
                  </svg>
                  Voice off
                </>
              ) : (
                <>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z" />
                  </svg>
                </>
              )}
            </button>
          )}
          {isActive && (
            <button className="rd-topbar-btn danger" onClick={goToExit}>
              End
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
            stage={state.stage}
            safetyChecking={state.safetyChecking}
          />

          {/* Captured pose thumbnail */}
          {state.capturedFrame && state.stage !== 'LISTENING' && state.stage !== 'FOLLOWING' && (
            <div className="rd-capture-wrap">
              <div className="rd-capture-label">Pose I saw</div>
              <div className="rd-capture-stage">
                <img
                  className="rd-capture-frame"
                  src={`data:image/jpeg;base64,${state.capturedFrame}`}
                  alt="Captured pose"
                />
              </div>
            </div>
          )}

          {/* Chat messages */}
          <AgentLiveRegion messages={state.messages} />
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
                <div className="rd-pose-empty">
                  <div className="rd-pose-empty-title">No poses yet!</div>
                  <div className="rd-pose-empty-hint">Say "capture my pose" and strike your favorite move to save it here.</div>
                </div>
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

      {/* Command help overlay */}
      {showCommands && (
        <CommandHelpModal
          examples={examples}
          onSelect={(text) => {
            setShowCommands(false)
            injectText(text)
          }}
          onClose={() => setShowCommands(false)}
        />
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

      {/* Intent approval modal — voice yes/no or buttons. */}
      {state.pendingIntent && (
        <div className="rd-overlay">
          <div className="rd-overlay-card">
            <div className="rd-overlay-title">Is this right?</div>
            <div className="rd-intent-label">What I'll do</div>
            <div className="rd-intent-pill">{state.pendingIntent}</div>
            <div className="rd-intent-hint">Say yes or no, or tap a button.</div>
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
  stage,
  safetyChecking,
}: {
  orbState: 'listening' | 'thinking' | 'countdown' | 'muted'
  statusText: string
  micLevel: number
  stage: string
  safetyChecking: boolean
}) {
  const badge = stageBadge(stage, orbState, safetyChecking)
  return (
    <div className="rd-orb-section">
      <div className={`rd-stage-badge rd-stage-${badge.className}`} aria-live="polite">
        <span className="rd-stage-badge-dot" />
        {badge.label}
      </div>
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

function stageBadge(
  stage: string,
  orbState: 'listening' | 'thinking' | 'countdown' | 'muted',
  safetyChecking: boolean,
): { label: string; className: string } {
  if (safetyChecking) return { label: 'Safety check…', className: 'thinking' }
  if (stage === 'COUNTDOWN') return { label: 'Countdown', className: 'countdown' }
  if (stage === 'CAPTURED') return { label: 'Captured!', className: 'success' }
  if (orbState === 'thinking') return { label: 'Thinking…', className: 'thinking' }
  if (orbState === 'countdown') return { label: 'Countdown', className: 'countdown' }
  if (orbState === 'muted') return { label: 'Muted', className: 'muted' }
  if (stage === 'FOLLOWING') return { label: 'Following', className: 'listening' }
  return { label: 'Listening…', className: 'listening' }
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

function AgentLiveRegion({ messages }: { messages: RefinedChatMsg[] }) {
  const lastAgent = [...messages].reverse().find((m) => m.role === 'agent')
  return (
    <div className="sr-only" aria-live="polite" aria-atomic="true">
      {lastAgent?.text ?? ''}
    </div>
  )
}

function ConnectionHealthDot({ services }: { services: ReturnType<typeof useConnectionStatus> }) {
  const allOk = services.every((s) => s.ok === true)
  const anyDown = services.some((s) => s.ok === false)
  const statusClass = allOk ? 'ok' : anyDown ? 'down' : 'pending'

  return (
    <div className="rd-health-dot" title={`Services: ${services.map((s) => `${s.name} ${s.ok === true ? 'ok' : s.ok === false ? 'down' : '…'}`).join(', ')}`}>
      <span className={`rd-health-dot-ping rd-health-dot-${statusClass}`} />
      <span className="rd-health-dot-label">{allOk ? 'Connected' : anyDown ? 'Reconnecting' : '…'}</span>
    </div>
  )
}

function CommandHelpModal({
  examples,
  onSelect,
  onClose,
}: {
  examples: { motion: string[]; immediate: string[]; conversation: string[] }
  onSelect: (text: string) => void
  onClose: () => void
}) {
  return (
    <div className="rd-overlay" onClick={onClose}>
      <div className="rd-overlay-card rd-command-card" onClick={(e) => e.stopPropagation()}>
        <div className="rd-overlay-title">What can I say?</div>
        <div className="rd-command-sections">
          <CommandSection title="Move my body" icon="🦾" phrases={examples.motion} onSelect={onSelect} />
          <CommandSection title="Play with poses" icon="🤸" phrases={examples.immediate} onSelect={onSelect} />
          <CommandSection title="Chat" icon="💬" phrases={examples.conversation} onSelect={onSelect} />
        </div>
        <div className="rd-overlay-btns">
          <button className="rd-overlay-btn secondary" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  )
}

function CommandSection({
  title,
  icon,
  phrases,
  onSelect,
}: {
  title: string
  icon: string
  phrases: string[]
  onSelect: (text: string) => void
}) {
  if (!phrases.length) return null
  return (
    <div className="rd-command-section">
      <div className="rd-command-section-title">
        <span>{icon}</span> {title}
      </div>
      <div className="rd-command-chips">
        {phrases.map((phrase) => (
          <button key={phrase} className="rd-command-chip" onClick={() => onSelect(phrase)}>
            {phrase}
          </button>
        ))}
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
        {msg.audioUrl && (
          <button
            className="rd-audio-play-btn"
            onClick={() => new Audio(msg.audioUrl).play()}
            title={msg.role === 'child' ? 'Play recording' : 'Play robot voice'}
            aria-label={msg.role === 'child' ? 'Play recording' : 'Play robot voice'}
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
