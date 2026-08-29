import { useReducer, useEffect, useRef, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { getRobotStream } from '../demo/robotConfig'
import {
  openActionSession,
  captureUtterance,
  sendAudioForTranscript,
  resetPose,
  mapFeatures,
  move,
  saveCurrentPose,
  setRobotState,
  sleep,
  classifyIntent,
  playShutter,
  type ActionSession,
  type ActionResult,
  type MapFeaturesResult,
  type IntentResult,
} from '../demo/api'
import RobotViewer from '../components/RobotViewer'
import AIReasoningStepper, { type StepItem } from '../components/AIReasoningStepper'
import './Tutorial.css'

const ROBOT_NAME = 'CORAL'

export type Screen =
  | 'welcome'
  | 'sim-playground'
  | 'concept-joints'
  | 'concept-intent'
  | 'concept-safety'
  | 'concept-follow'
  | 'concept-save'
  | 'free-practice'
  | 'ready'

type VoicePhase = 'idle' | 'listening' | 'thinking' | 'done' | 'error'
type CapturePhase = 'idle' | 'countdown' | 'analyzing' | 'result' | 'naming' | 'saved'

interface StepperState {
  command?: string
  understanding?: string
  safety?: { ok: boolean; reason?: string }
  clarification?: string
  execute?: string
}

interface State {
  screen: Screen
  // sim playground progress
  blockPart: string | null
  blockDir: string | null
  blockChecking: boolean
  blockConfirmed: boolean
  // voice / stepper state
  voicePhase: VoicePhase
  transcript: string
  error: string
  stepper: StepperState
  // follow / capture
  following: boolean
  captured: MapFeaturesResult | null
  capturePhase: CapturePhase
  countdown: number | null
  savedName: string
  // free practice
  practiceReady: boolean
  // facilitator overlay
  facilitatorOpen: boolean
  sessionLog: string[]
}

type Action =
  | { type: 'GO'; screen: Screen }
  | { type: 'SET_BLOCK_PART'; val: string | null }
  | { type: 'SET_BLOCK_DIR'; val: string | null }
  | { type: 'BLOCK_CHECKING' }
  | { type: 'BLOCK_CONFIRMED' }
  | { type: 'BLOCK_RESET' }
  | { type: 'SET_VOICE_PHASE'; phase: VoicePhase }
  | { type: 'SET_TRANSCRIPT'; text: string }
  | { type: 'SET_ERROR'; text: string }
  | { type: 'SET_STEPPER'; stepper: StepperState }
  | { type: 'CLEAR_STEPPER' }
  | { type: 'SET_FOLLOWING'; active: boolean }
  | { type: 'SET_CAPTURED'; result: MapFeaturesResult | null }
  | { type: 'SET_CAPTURE_PHASE'; phase: CapturePhase }
  | { type: 'SET_COUNTDOWN'; n: number | null }
  | { type: 'SET_SAVED_NAME'; name: string }
  | { type: 'MARK_PRACTICE_READY' }
  | { type: 'TOGGLE_FACILITATOR' }
  | { type: 'LOG'; text: string }

const SCREENS: Screen[] = [
  'welcome',
  'sim-playground',
  'concept-joints',
  'concept-intent',
  'concept-safety',
  'concept-follow',
  'concept-save',
  'free-practice',
  'ready',
]

function reducer(s: State, a: Action): State {
  switch (a.type) {
    case 'GO':
      return {
        ...s,
        screen: a.screen,
        voicePhase: 'idle',
        transcript: '',
        error: '',
        stepper: {},
        countdown: null,
        capturePhase: 'idle',
        // Preserve captured image when flowing follow -> save, otherwise reset is fine.
      }
    case 'SET_BLOCK_PART':
      return { ...s, blockPart: a.val, blockConfirmed: false, blockChecking: false }
    case 'SET_BLOCK_DIR':
      return { ...s, blockDir: a.val, blockConfirmed: false, blockChecking: false }
    case 'BLOCK_CHECKING':
      return { ...s, blockChecking: true, blockConfirmed: false }
    case 'BLOCK_CONFIRMED':
      return { ...s, blockChecking: false, blockConfirmed: true }
    case 'BLOCK_RESET':
      return { ...s, blockPart: null, blockDir: null, blockConfirmed: false, blockChecking: false }
    case 'SET_VOICE_PHASE':
      return { ...s, voicePhase: a.phase }
    case 'SET_TRANSCRIPT':
      return { ...s, transcript: a.text }
    case 'SET_ERROR':
      return { ...s, error: a.text }
    case 'SET_STEPPER':
      return { ...s, stepper: { ...s.stepper, ...a.stepper } }
    case 'CLEAR_STEPPER':
      return { ...s, stepper: {} }
    case 'SET_FOLLOWING':
      return { ...s, following: a.active }
    case 'SET_CAPTURED':
      return { ...s, captured: a.result }
    case 'SET_CAPTURE_PHASE':
      return { ...s, capturePhase: a.phase }
    case 'SET_COUNTDOWN':
      return { ...s, countdown: a.n }
    case 'SET_SAVED_NAME':
      return { ...s, savedName: a.name }
    case 'MARK_PRACTICE_READY':
      return { ...s, practiceReady: true }
    case 'TOGGLE_FACILITATOR':
      return { ...s, facilitatorOpen: !s.facilitatorOpen }
    case 'LOG':
      return { ...s, sessionLog: [...s.sessionLog.slice(-19), a.text] }
    default:
      return s
  }
}

const initState: State = {
  screen: 'welcome',
  blockPart: null,
  blockDir: null,
  blockChecking: false,
  blockConfirmed: false,
  voicePhase: 'idle',
  transcript: '',
  error: '',
  stepper: {},
  following: false,
  captured: null,
  capturePhase: 'idle',
  countdown: null,
  savedName: '',
  practiceReady: false,
  facilitatorOpen: false,
  sessionLog: [],
}

// ---- Shared visual components ----

function RobotIllustration({ wave = false, happy = false }: { wave?: boolean; happy?: boolean }) {
  return (
    <div className="tut-robot">
      <div className="tut-robot-neck-wrap">
        <div className="tut-robot-antenna" />
        <div className="tut-robot-neck" />
      </div>
      <div className="tut-robot-head">
        <div className={`tut-robot-eye ${happy ? 'tut-robot-eye-happy' : 'tut-robot-eye-normal'}`} />
        <div className={`tut-robot-eye ${happy ? 'tut-robot-eye-happy' : 'tut-robot-eye-normal'}`} />
      </div>
      <div className="tut-robot-torso-wrap">
        <div className="tut-robot-torso">
          <div className="tut-robot-chest">
            <div className="tut-robot-bar" style={{ width: 6, height: 14 }} />
            <div className="tut-robot-bar" style={{ width: 6, height: 26 }} />
            <div className="tut-robot-bar" style={{ width: 6, height: 18 }} />
            <div className="tut-robot-bar" style={{ width: 6, height: 10 }} />
          </div>
        </div>
        <div className={`tut-robot-arm tut-robot-arm-left${wave ? ' tut-robot-arm-wave' : ''}`}>
          <div className="tut-robot-joint" />
          <div className="tut-robot-limb" />
        </div>
        <div className="tut-robot-arm tut-robot-arm-right">
          <div className="tut-robot-joint" />
          <div className="tut-robot-limb" />
        </div>
      </div>
      <div className="tut-robot-legs">
        <div className="tut-robot-leg" />
        <div className="tut-robot-leg" />
      </div>
    </div>
  )
}

const CONFETTI_COLORS = ['#FF6B4A', '#17BEBB', '#F0A93A', '#7C6CF0', '#EF6F9C', '#3FA76B']

function Confetti() {
  const bits = Array.from({ length: 16 }).map((_, i) => ({
    left: `${5 + i * 5.8}%`,
    width: 10 + (i % 3) * 5,
    height: 14 + (i % 4) * 4,
    background: CONFETTI_COLORS[i % CONFETTI_COLORS.length],
    animationDuration: `${1.4 + (i % 5) * 0.3}s`,
    animationDelay: `${(i % 7) * 0.12}s`,
    animationFillMode: 'both' as const,
  }))
  return (
    <div className="tut-confetti-wrap">
      {bits.map((b, i) => (
        <div
          key={i}
          className="tut-confetti-bit"
          style={{
            left: b.left,
            width: b.width,
            height: b.height,
            background: b.background,
            animationDuration: b.animationDuration,
            animationDelay: b.animationDelay,
            animationFillMode: b.animationFillMode,
          }}
        />
      ))}
    </div>
  )
}

function SimPanel({
  caption,
  cameraUrl,
  overlay,
}: {
  caption?: string
  cameraUrl?: string
  overlay?: React.ReactNode
}) {
  const [feedReady, setFeedReady] = useState(false)
  useEffect(() => { setFeedReady(false) }, [cameraUrl])

  return (
    <div className="tut-sim">
      <div className="tut-sim-grid" />
      <div className="tut-sim-vignette" />
      <div className="tut-sim-floor" />
      <div className="tut-sim-badge-top">
        <span className="tut-sim-badge-dot" />
        SIM
      </div>
      <div className="tut-sim-safety">
        <span
          style={{
            width: 10,
            height: 10,
            borderRadius: '50%',
            background: '#3FA76B',
            boxShadow: '0 0 10px #3FA76B',
            display: 'inline-block',
          }}
        />
        Safe zone
      </div>
      <RobotViewer embedded />
      {caption && (
        <div className="tut-sim-caption">
          <div className="tut-sim-caption-pill">{caption}</div>
        </div>
      )}
      {overlay}
      <div className="tut-pip">
        {cameraUrl && (
          <img
            src={cameraUrl}
            style={{
              position: 'absolute',
              inset: 0,
              width: '100%',
              height: '100%',
              objectFit: 'cover',
              borderRadius: 14,
            }}
            onLoad={() => setFeedReady(true)}
            onError={() => setFeedReady(false)}
            alt="camera"
          />
        )}
        <div className="tut-pip-live">
          <span className="tut-pip-live-dot" />
          <span className="tut-pip-live-text">LIVE</span>
        </div>
        {!feedReady && (
          <>
            <div className="tut-pip-icon" />
            <div className="tut-pip-label">[ live camera feed ]</div>
          </>
        )}
      </div>
    </div>
  )
}

function AgentBubble({ children }: { children: React.ReactNode }) {
  return (
    <div className="tut-agent-bubble">
      <div className="tut-agent-header">
        <span className="tut-agent-dot" />
        <span className="tut-agent-name">{ROBOT_NAME}'S HELPER</span>
      </div>
      <div className="tut-agent-script">{children}</div>
    </div>
  )
}

function MicOrb({
  phase,
  onClick,
  label,
}: {
  phase: VoicePhase
  onClick?: () => void
  label?: string
}) {
  return (
    <div className="tut-mic-wrap">
      <div className="tut-orb-container" onClick={phase === 'idle' ? onClick : undefined} style={{ cursor: phase === 'idle' ? 'pointer' : 'default' }}>
        <span className="tut-orb-ring" />
        <span className="tut-orb-ring tut-orb-ring2" />
        <div className="tut-orb-core">
          <div className="tut-orb-mic">
            <div className="tut-orb-mic-body" />
            <div className="tut-orb-mic-base" />
            <div className="tut-orb-mic-stem" />
          </div>
        </div>
      </div>
      {phase === 'idle' && label && <div className="tut-orb-listen-label">{label}</div>}
      {phase === 'listening' && (
        <div className="tut-orb-listen-label">
          <span className="tut-orb-listen-dot" />
          Listening…
        </div>
      )}
      {phase === 'thinking' && <div className="tut-orb-listen-label">Thinking…</div>}
    </div>
  )
}

function SuggestedChips({ prompts, onPrompt }: { prompts: string[]; onPrompt: (p: string) => void }) {
  return (
    <div className="tut-chips">
      {prompts.map((p) => (
        <button key={p} className="tut-chip tut-chip-unsel" onClick={() => onPrompt(p)}>
          "{p}"
        </button>
      ))}
    </div>
  )
}

function TranscriptBox({ text }: { text: string }) {
  if (!text) return null
  return (
    <div className="tut-transcript">
      <div className="tut-transcript-label">YOU SAID</div>
      <div className="tut-transcript-text">"{text}"</div>
    </div>
  )
}

function buildStepperItems(stepper: StepperState): StepItem[] {
  const items: StepItem[] = [
    { id: 'command', label: 'Your command', state: stepper.command ? 'success' : 'upcoming', detail: stepper.command },
    { id: 'understanding', label: 'Understanding', state: 'upcoming' },
    { id: 'safety', label: 'Safety check', state: 'upcoming' },
    { id: 'clarification', label: 'Clarification', state: 'upcoming' },
    { id: 'execute', label: 'Execute', state: 'upcoming' },
  ]
  if (stepper.understanding) {
    items[1] = { id: 'understanding', label: 'Understanding', state: 'success', detail: stepper.understanding }
  }
  if (stepper.safety) {
    items[2] = {
      id: 'safety',
      label: 'Safety check',
      state: stepper.safety.ok ? 'success' : 'blocked',
      detail: stepper.safety.ok ? stepper.safety.reason ?? 'All clear!' : stepper.safety.reason ?? 'Blocked',
    }
  }
  if (stepper.clarification) {
    items[3] = { id: 'clarification', label: 'Clarification', state: 'active', detail: stepper.clarification }
  } else if (stepper.understanding && stepper.safety?.ok) {
    items[3] = { id: 'clarification', label: 'Clarification', state: 'skipped' }
  }
  if (stepper.execute) {
    items[4] = { id: 'execute', label: 'Execute', state: 'success', detail: stepper.execute }
  }
  // Active inference: if command exists but understanding doesn't, understanding is active.
  if (stepper.command && !stepper.understanding && !stepper.safety && !stepper.execute) {
    items[1] = { id: 'understanding', label: 'Understanding', state: 'active', detail: 'Figuring out what you mean…' }
  }
  if (stepper.understanding && !stepper.safety && !stepper.execute) {
    items[2] = { id: 'safety', label: 'Safety check', state: 'active', detail: 'Checking the simulator…' }
  }
  if (stepper.safety?.ok && !stepper.clarification && !stepper.execute) {
    items[4] = { id: 'execute', label: 'Execute', state: 'active', detail: 'Moving now…' }
  }
  return items
}

// ---- Screen components ----

function WelcomeScreen({ onStart, onSkip }: { onStart: () => void; onSkip: () => void }) {
  return (
    <div className="tut-welcome">
      <div className="tut-welcome-grid" />
      <div className="tut-welcome-logo">
        <div className="tut-logo-box">
          <div className="tut-logo-diamond" />
        </div>
        <div>
          <div className="tut-logo-name">{ROBOT_NAME}</div>
          <div className="tut-logo-sub">TUTORIAL</div>
        </div>
      </div>
      <div className="tut-welcome-robot">
        <RobotIllustration />
      </div>
      <div className="tut-welcome-bubble">
        <div className="tut-welcome-title">
          Hey! I'm {ROBOT_NAME}'s helper. Today, <span style={{ color: 'var(--accent)' }}>YOU</span> get to be the robot teacher.
        </div>
        <div className="tut-welcome-sub">Before we meet the real robot, let's practice in the simulator first.</div>
      </div>
      <div className="tut-welcome-btns">
        <button className="tut-welcome-cta" onClick={onStart}>
          Let's explore!
        </button>
        <button className="tut-welcome-skip" onClick={onSkip}>
          Skip →
        </button>
      </div>
    </div>
  )
}

function SimPlaygroundScreen({
  s,
  dispatch,
  cameraUrl,
  onNext,
  runBlockMove,
}: {
  s: State
  dispatch: React.Dispatch<Action>
  cameraUrl: string
  onNext: () => void
  runBlockMove: (part: string, dir: string) => Promise<void>
}) {
  const partOptions = ['Shoulder', 'Elbow', 'Wrist', 'Hip']
  const dirOptions = ['Raise', 'Lower', 'Extend', 'Bend']
  const bothSet = !!s.blockPart && !!s.blockDir
  const moveText = bothSet ? `${s.blockDir} ${s.blockPart}` : ''

  return (
    <>
      <div className="tut-colheader">
        <div className="tut-colheader-left">
          <div className="tut-logo-box">
            <div className="tut-logo-diamond" />
          </div>
          <span className="tut-badge tut-badge-explore">EXPLORE</span>
          <div className="tut-colheader-title">Simulator Playground</div>
        </div>
        <button className="tut-skip-btn" onClick={onNext}>
          Skip →
        </button>
      </div>

      <div className="tut-twocol">
        <SimPanel cameraUrl={cameraUrl} />
        <div className="tut-right">
          <div className="tut-right-scroll">
            <AgentBubble>
              This is a simulator — it moves just like the real {ROBOT_NAME} would. Try clicking a body part and dragging the ring to rotate it. That's a joint!
            </AgentBubble>

            <div className="tut-intent-tip">
              <span className="tut-intent-tip-dot" />
              Tip: green ring = safe, yellow = near the limit, red = blocked.
            </div>

            <div className="tut-blocks-header">
              <div className="tut-blocks-title">Or build a move, block by block</div>
            </div>
            <div className="tut-blocks-body">
              {/* Block 1 */}
              <div className={`tut-block-row ${s.blockPart ? 'tut-block-row-done' : 'tut-block-row-active'}`}>
                <div className="tut-block-inner">
                  <div className={`tut-block-num ${s.blockPart ? 'tut-block-num-done' : 'tut-block-num-active'}`}>1</div>
                  <div style={{ flex: 1 }}>
                    <div className="tut-block-label tut-block-label-on">Pick a body part</div>
                    <div className="tut-block-req">Needs: which joint</div>
                  </div>
                  {s.blockPart && <div className="tut-block-value">{s.blockPart}</div>}
                </div>
                <div className="tut-chips">
                  {partOptions.map((o) => (
                    <button
                      key={o}
                      className={`tut-chip ${s.blockPart === o ? 'tut-chip-sel' : 'tut-chip-unsel'}`}
                      onClick={() => dispatch({ type: 'SET_BLOCK_PART', val: o })}
                    >
                      {o}
                    </button>
                  ))}
                </div>
              </div>

              {/* Block 2 */}
              <div
                className={`tut-block-row ${
                  !s.blockPart ? 'tut-block-row-waiting' : s.blockDir ? 'tut-block-row-done' : 'tut-block-row-active'
                }`}
              >
                <div className="tut-block-inner">
                  <div
                    className={`tut-block-num ${
                      !s.blockPart ? 'tut-block-num-waiting' : s.blockDir ? 'tut-block-num-done' : 'tut-block-num-active'
                    }`}
                  >
                    2
                  </div>
                  <div style={{ flex: 1 }}>
                    <div className={`tut-block-label ${s.blockPart ? 'tut-block-label-on' : 'tut-block-label-off'}`}>
                      Set a direction
                    </div>
                    <div className="tut-block-req">Needs: which way</div>
                  </div>
                  {s.blockDir && <div className="tut-block-value">{s.blockDir}</div>}
                </div>
                {s.blockPart && (
                  <div className="tut-chips">
                    {dirOptions.map((o) => (
                      <button
                        key={o}
                        className={`tut-chip ${s.blockDir === o ? 'tut-chip-sel' : 'tut-chip-unsel'}`}
                        onClick={() => dispatch({ type: 'SET_BLOCK_DIR', val: o })}
                      >
                        {o}
                      </button>
                    ))}
                  </div>
                )}
                {!s.blockPart && <div className="tut-waiting-text">Finish the block above first.</div>}
              </div>

              {/* Block 3 */}
              <div className={`tut-block-row ${!bothSet ? 'tut-block-row-waiting' : 'tut-block-row-active'}`}>
                <div className="tut-block-inner">
                  <div className={`tut-block-num ${bothSet ? 'tut-block-num-active' : 'tut-block-num-waiting'}`}>3</div>
                  <div style={{ flex: 1 }}>
                    <div className={`tut-block-label ${bothSet ? 'tut-block-label-on' : 'tut-block-label-off'}`}>
                      Confirm & simulate
                    </div>
                  </div>
                </div>
                {bothSet && !s.blockChecking && !s.blockConfirmed && (
                  <div className="tut-confirm-btns" style={{ marginTop: 13 }}>
                    <button
                      className="tut-btn-primary"
                      style={{ flex: 1 }}
                      onClick={() => runBlockMove(s.blockPart!, s.blockDir!)}
                    >
                      Execute motion
                    </button>
                  </div>
                )}
                {bothSet && s.blockChecking && (
                  <div className="tut-block-checking">
                    <div className="tut-checking-card">
                      <div className="tut-checking-spinner" />
                      <div className="tut-checking-text">Checking safety…</div>
                    </div>
                  </div>
                )}
                {bothSet && s.blockConfirmed && (
                  <>
                    <div className="tut-confirm-row" style={{ marginTop: 13 }}>
                      <div className="tut-confirm-check">✓</div>
                      <div className="tut-confirm-text">
                        <strong>{moveText}</strong> completed
                      </div>
                    </div>
                    <div className="tut-confirm-btns">
                      <button className="tut-btn-ghost" onClick={() => dispatch({ type: 'BLOCK_RESET' })}>
                        Another
                      </button>
                    </div>
                  </>
                )}
                {!bothSet && <div className="tut-waiting-text">Finish the blocks above first.</div>}
              </div>
            </div>

            <button className="tut-next-btn" onClick={onNext}>
              I got it! Next →
            </button>
          </div>
        </div>
      </div>
    </>
  )
}

function ConceptHeader({
  index,
  title,
  onSkip,
}: {
  index: number
  title: string
  onSkip: () => void
}) {
  const dots = [0, 1, 2, 3, 4].map((i) =>
    i === index ? 'tut-dot-active' : i < index ? 'tut-dot-done' : 'tut-dot-upcoming'
  )
  return (
    <div className="tut-colheader">
      <div className="tut-colheader-left">
        <div className="tut-logo-box">
          <div className="tut-logo-diamond" />
        </div>
        <div className="tut-dots">{dots.map((cls, i) => <span key={i} className={cls} />)}</div>
        <div className="tut-colheader-title">
          Concept {index + 1} of 5 · {title}
        </div>
      </div>
      <button className="tut-skip-btn" onClick={onSkip}>
        Skip →
      </button>
    </div>
  )
}

function ConceptJointsScreen({
  s,
  dispatch,
  cameraUrl,
  onNext,
  sendCommand,
}: {
  s: State
  dispatch: React.Dispatch<Action>
  cameraUrl: string
  onNext: () => void
  sendCommand: (text: string) => Promise<ActionResult>
}) {
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    return () => { abortRef.current?.abort() }
  }, [])

  const listen = async (_prompt: string) => {
    dispatch({ type: 'SET_ERROR', text: '' })
    dispatch({ type: 'SET_TRANSCRIPT', text: '' })
    dispatch({ type: 'CLEAR_STEPPER' })
    dispatch({ type: 'SET_VOICE_PHASE', phase: 'listening' })
    const ctrl = new AbortController()
    abortRef.current = ctrl
    try {
      const blob = await captureUtterance({ signal: ctrl.signal })
      dispatch({ type: 'SET_VOICE_PHASE', phase: 'thinking' })
      const text = await sendAudioForTranscript(blob)
      if (!text.trim()) {
        dispatch({ type: 'SET_ERROR', text: "I didn't catch that — try again!" })
        dispatch({ type: 'SET_VOICE_PHASE', phase: 'idle' })
        return
      }
      dispatch({ type: 'SET_TRANSCRIPT', text })
      dispatch({ type: 'SET_STEPPER', stepper: { command: text } })
      await sendCommand(text)
      dispatch({ type: 'SET_STEPPER', stepper: { understanding: `I think you want to: ${text}`, safety: { ok: true }, execute: 'Moved in the simulator' } })
      dispatch({ type: 'SET_VOICE_PHASE', phase: 'done' })
    } catch (err) {
      console.error('joints voice demo failed', err)
      dispatch({ type: 'SET_ERROR', text: 'Something went wrong — try again!' })
      dispatch({ type: 'SET_VOICE_PHASE', phase: 'idle' })
    }
  }

  const prompts = ['raise your right arm', 'look up', 'bend your left elbow']

  return (
    <>
      <ConceptHeader index={0} title="Joints & Movement" onSkip={onNext} />
      <div className="tut-twocol">
        <SimPanel cameraUrl={cameraUrl} />
        <div className="tut-right">
          <div className="tut-right-scroll">
            <AgentBubble>
              You just moved my joints by hand. Now try with your voice! Tap the mic and tell me what to do.
            </AgentBubble>

            <SuggestedChips prompts={prompts} onPrompt={listen} />

            <MicOrb phase={s.voicePhase} onClick={() => listen(prompts[0])} label='Tap and say "raise your right arm"' />

            <TranscriptBox text={s.transcript} />
            {s.error && <div className="tut-waiting-text">{s.error}</div>}

            <AIReasoningStepper steps={buildStepperItems(s.stepper)} />

            {s.voicePhase === 'done' && (
              <button className="tut-next-btn" onClick={onNext}>
                Got it! Next →
              </button>
            )}
          </div>
        </div>
      </div>
    </>
  )
}

function ConceptIntentScreen({
  s,
  dispatch,
  cameraUrl,
  onNext,
  sendCommand,
}: {
  s: State
  dispatch: React.Dispatch<Action>
  cameraUrl: string
  onNext: () => void
  sendCommand: (text: string) => Promise<ActionResult>
}) {
  const abortRef = useRef<AbortController | null>(null)
  const [intent, setIntent] = useState<IntentResult | null>(null)

  useEffect(() => {
    return () => { abortRef.current?.abort() }
  }, [])

  const listen = async () => {
    dispatch({ type: 'SET_ERROR', text: '' })
    dispatch({ type: 'SET_TRANSCRIPT', text: '' })
    dispatch({ type: 'CLEAR_STEPPER' })
    dispatch({ type: 'SET_VOICE_PHASE', phase: 'listening' })
    setIntent(null)
    const ctrl = new AbortController()
    abortRef.current = ctrl
    try {
      const blob = await captureUtterance({ signal: ctrl.signal })
      dispatch({ type: 'SET_VOICE_PHASE', phase: 'thinking' })
      const text = await sendAudioForTranscript(blob)
      if (!text.trim()) {
        dispatch({ type: 'SET_ERROR', text: "I didn't catch that — try again!" })
        dispatch({ type: 'SET_VOICE_PHASE', phase: 'idle' })
        return
      }
      dispatch({ type: 'SET_TRANSCRIPT', text })
      dispatch({ type: 'SET_STEPPER', stepper: { command: text } })
      const result = await classifyIntent(text, false, undefined, 'tutorial-intent')
      dispatch({ type: 'LOG', text: `intent: ${result.type} — ${JSON.stringify(result)}` })
      setIntent(result)
      const understanding = intentDescription(result)
      dispatch({ type: 'SET_STEPPER', stepper: { understanding } })
      dispatch({ type: 'SET_VOICE_PHASE', phase: 'idle' })
    } catch (err) {
      console.error('intent demo failed', err)
      dispatch({ type: 'SET_ERROR', text: 'Something went wrong — try again!' })
      dispatch({ type: 'SET_VOICE_PHASE', phase: 'idle' })
    }
  }

  const execute = async (text: string) => {
    dispatch({ type: 'SET_VOICE_PHASE', phase: 'thinking' })
    try {
      await sendCommand(text)
      dispatch({ type: 'SET_STEPPER', stepper: { safety: { ok: true }, execute: 'Moved in the simulator' } })
      dispatch({ type: 'SET_VOICE_PHASE', phase: 'done' })
    } catch (err) {
      dispatch({ type: 'SET_ERROR', text: 'Could not run that move — try again.' })
      dispatch({ type: 'SET_VOICE_PHASE', phase: 'idle' })
    }
  }

  const correct = (side: string) => {
    const corrected = `${s.transcript} — ${side}`
    dispatch({ type: 'SET_TRANSCRIPT', text: corrected })
    dispatch({ type: 'CLEAR_STEPPER' })
    dispatch({ type: 'SET_STEPPER', stepper: { command: corrected, understanding: `I think you want to ${side}` } })
    execute(corrected)
  }

  const prompts = ['move the arm up', 'raise your arm']

  return (
    <>
      <ConceptHeader index={1} title="Instructions & Intent" onSkip={onNext} />
      <div className="tut-twocol">
        <SimPanel cameraUrl={cameraUrl} />
        <div className="tut-right">
          <div className="tut-right-scroll">
            <AgentBubble>
              Sometimes I'm not sure what you mean. I'll show you my best guess, and you can fix it if I'm wrong.
            </AgentBubble>

            {!intent && s.voicePhase !== 'done' && (
              <>
                <SuggestedChips prompts={prompts} onPrompt={() => listen()} />
                <MicOrb phase={s.voicePhase} onClick={listen} label='Tap and say "move the arm up"' />
              </>
            )}

            <TranscriptBox text={s.transcript} />
            {s.error && <div className="tut-waiting-text">{s.error}</div>}

            {intent && s.voicePhase !== 'done' && (
              <div className="tut-intent-card">
                <div className="tut-intent-header">
                  <div className="tut-intent-icon">?</div>
                  <span className="tut-intent-label">MY BEST GUESS</span>
                </div>
                <div className="tut-intent-text">{intentDescription(intent)}</div>
                <div className="tut-intent-btns">
                  <button className="tut-btn-primary" onClick={() => execute(s.transcript)}>
                    Yes, do it
                  </button>
                  <button className="tut-btn-ghost" onClick={() => correct('use the left arm')}>
                    No, left arm
                  </button>
                  <button className="tut-btn-ghost" onClick={() => correct('use the right arm')}>
                    Right arm
                  </button>
                </div>
              </div>
            )}

            <AIReasoningStepper steps={buildStepperItems(s.stepper)} />

            {s.voicePhase === 'done' && (
              <>
                <div className="tut-intent-tip">
                  <span className="tut-intent-tip-dot" />
                  I'm making a guess — I can't read your mind! You can always correct me.
                </div>
                <button className="tut-next-btn" onClick={onNext}>
                  Got it! Next →
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </>
  )
}

function intentDescription(result: IntentResult): string {
  if (result.type === 'motion') return `I think you want to: ${result.description}`
  if (result.type === 'clarification') return `I'm not sure — ${result.question}`
  if (result.type === 'immediate') return `I understood: ${result.intent}`
  return `I heard: "${result.text}"`
}

function ConceptSafetyScreen({
  s,
  dispatch,
  cameraUrl,
  onNext,
  sendCommand,
}: {
  s: State
  dispatch: React.Dispatch<Action>
  cameraUrl: string
  onNext: () => void
  sendCommand: (text: string) => Promise<ActionResult>
}) {
  const abortRef = useRef<AbortController | null>(null)
  const didReset = useRef(false)

  useEffect(() => {
    if (didReset.current) return
    didReset.current = true
    resetPose().catch(() => {})
    return () => { abortRef.current?.abort() }
  }, [])

  const prompt = 'rotate your right arm all the way into your stomach'

  const listen = async () => {
    dispatch({ type: 'SET_ERROR', text: '' })
    dispatch({ type: 'SET_TRANSCRIPT', text: '' })
    dispatch({ type: 'CLEAR_STEPPER' })
    dispatch({ type: 'SET_VOICE_PHASE', phase: 'listening' })
    const ctrl = new AbortController()
    abortRef.current = ctrl
    try {
      const blob = await captureUtterance({ signal: ctrl.signal })
      dispatch({ type: 'SET_VOICE_PHASE', phase: 'thinking' })
      const text = await sendAudioForTranscript(blob)
      if (!text.trim()) {
        dispatch({ type: 'SET_ERROR', text: "I didn't catch that — try again!" })
        dispatch({ type: 'SET_VOICE_PHASE', phase: 'idle' })
        return
      }
      dispatch({ type: 'SET_TRANSCRIPT', text })
      dispatch({ type: 'SET_STEPPER', stepper: { command: text, understanding: 'Rotate right arm inward' } })
      await sendCommand(text)
      dispatch({
        type: 'SET_STEPPER',
        stepper: {
          safety: {
            ok: false,
            reason: `${ROBOT_NAME}'s arm would bump into its own body, so the safety checker stopped it short.`,
          },
        },
      })
      dispatch({ type: 'SET_VOICE_PHASE', phase: 'done' })
    } catch (err) {
      console.error('safety demo failed', err)
      dispatch({ type: 'SET_ERROR', text: 'Something went wrong — try again!' })
      dispatch({ type: 'SET_VOICE_PHASE', phase: 'idle' })
    }
  }

  return (
    <>
      <ConceptHeader index={2} title="Safety Checks" onSkip={onNext} />
      <div className="tut-twocol">
        <SimPanel cameraUrl={cameraUrl} />
        <div className="tut-right">
          <div className="tut-right-scroll">
            <AgentBubble>
              I always check a move is safe before I try it. First I'll stand back up — then ask me to rotate my right arm all the way into my stomach and watch what happens.
            </AgentBubble>

            <SuggestedChips prompts={[prompt]} onPrompt={() => listen()} />
            <MicOrb phase={s.voicePhase} onClick={listen} label={`Tap and say "${prompt}"`} />

            <TranscriptBox text={s.transcript} />
            {s.error && <div className="tut-waiting-text">{s.error}</div>}

            <AIReasoningStepper steps={buildStepperItems(s.stepper)} />

            {s.voicePhase === 'done' && (
              <>
                <div className="tut-intent-tip">
                  <span className="tut-intent-tip-dot" />
                  Before every move, the simulator runs a collision checker so nobody gets hurt.
                </div>
                <button className="tut-next-btn" onClick={onNext}>
                  Got it! Next →
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </>
  )
}

function ConceptFollowScreen({
  s,
  dispatch,
  cameraUrl,
  onNext,
  session,
}: {
  s: State
  dispatch: React.Dispatch<Action>
  cameraUrl: string
  onNext: () => void
  session: React.MutableRefObject<ActionSession | null>
}) {
  const startFollowing = async () => {
    dispatch({ type: 'SET_ERROR', text: '' })
    dispatch({ type: 'SET_FOLLOWING', active: true })
    try {
      await session.current?.sendText('follow my movement', 'immediate')
    } catch (err) {
      console.error('follow start failed', err)
      dispatch({ type: 'SET_ERROR', text: "Couldn't start following — try again." })
      dispatch({ type: 'SET_FOLLOWING', active: false })
    }
  }

  const capture = async () => {
    if (!session.current) return
    dispatch({ type: 'SET_ERROR', text: '' })
    dispatch({ type: 'SET_CAPTURE_PHASE', phase: 'countdown' })
    dispatch({ type: 'SET_COUNTDOWN', n: 3 })
    try {
      await setRobotState('DEMO_LOCKED')
      for (const n of [3, 2, 1]) {
        dispatch({ type: 'SET_COUNTDOWN', n })
        await sleep(1000)
      }
      dispatch({ type: 'SET_COUNTDOWN', n: null })
      dispatch({ type: 'SET_CAPTURE_PHASE', phase: 'analyzing' })
      playShutter()
      const result = await mapFeatures()
      if (!result.poseDetected) {
        await setRobotState('IDLE')
        dispatch({ type: 'SET_ERROR', text: result.detail || "I couldn't see your whole body — step back!" })
        dispatch({ type: 'SET_CAPTURE_PHASE', phase: 'idle' })
        return
      }
      await move(result.commands)
      await setRobotState('IDLE')
      dispatch({ type: 'SET_CAPTURED', result })
      dispatch({ type: 'SET_CAPTURE_PHASE', phase: 'result' })
      dispatch({ type: 'SET_FOLLOWING', active: false })
      // Move on to save concept automatically after a brief pause.
      await sleep(1200)
      onNext()
    } catch (err) {
      console.error('follow capture failed', err)
      await setRobotState('IDLE')
      dispatch({ type: 'SET_ERROR', text: 'Something went wrong — try again!' })
      dispatch({ type: 'SET_CAPTURE_PHASE', phase: 'idle' })
    }
  }

  useEffect(() => {
    return () => {
      if (s.following) setRobotState('IDLE').catch(() => {})
    }
  }, [])

  return (
    <>
      <ConceptHeader index={3} title="Follow My Movement" onSkip={onNext} />
      <div className="tut-twocol">
        <SimPanel
          cameraUrl={cameraUrl}
          overlay={
            s.capturePhase === 'countdown' && s.countdown != null ? (
              <div className="tut-capture-countdown">
                <span key={s.countdown}>{s.countdown}</span>
              </div>
            ) : s.capturePhase === 'analyzing' ? (
              <div className="tut-capture-analyzing">
                <div className="tut-checking-spinner" />
                <div className="tut-checking-text">Reading your pose…</div>
              </div>
            ) : s.following ? (
              <div className="tut-follow-badge">
                <span className="tut-follow-dot" />
                <span>Mirroring your moves</span>
              </div>
            ) : null
          }
        />
        <div className="tut-right">
          <div className="tut-right-scroll">
            <AgentBubble>
              I can copy the way you move! Stand back so I can see your whole body, then tap Start following.
            </AgentBubble>

            {!s.following && s.capturePhase === 'idle' && (
              <button className="tut-next-btn" onClick={startFollowing}>
                Start following ▶
              </button>
            )}

            {s.following && (
              <>
                <div className="tut-success-card">
                  <div className="tut-check-icon">✓</div>
                  <div className="tut-success-text">I'm mirroring you! Strike a pose, then tap Capture.</div>
                </div>
                <button className="tut-next-btn" onClick={capture}>
                  Capture this pose 📷
                </button>
              </>
            )}

            {s.error && <div className="tut-waiting-text">{s.error}</div>}
          </div>
        </div>
      </div>
    </>
  )
}

function ConceptSaveScreen({
  s,
  dispatch,
  cameraUrl,
  onNext,
}: {
  s: State
  dispatch: React.Dispatch<Action>
  cameraUrl: string
  onNext: () => void
}) {
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    return () => { abortRef.current?.abort() }
  }, [])

  const runCapture = async () => {
    dispatch({ type: 'SET_ERROR', text: '' })
    dispatch({ type: 'SET_CAPTURE_PHASE', phase: 'countdown' })
    dispatch({ type: 'SET_COUNTDOWN', n: 3 })
    try {
      await setRobotState('DEMO_LOCKED')
      for (const n of [3, 2, 1]) {
        dispatch({ type: 'SET_COUNTDOWN', n })
        await sleep(1000)
      }
      dispatch({ type: 'SET_COUNTDOWN', n: null })
      dispatch({ type: 'SET_CAPTURE_PHASE', phase: 'analyzing' })
      playShutter()
      const result = await mapFeatures()
      if (!result.poseDetected) {
        await setRobotState('IDLE')
        dispatch({ type: 'SET_ERROR', text: result.detail || "I couldn't see your whole body — step back!" })
        dispatch({ type: 'SET_CAPTURE_PHASE', phase: 'idle' })
        return
      }
      await move(result.commands)
      await setRobotState('IDLE')
      dispatch({ type: 'SET_CAPTURED', result })
      dispatch({ type: 'SET_CAPTURE_PHASE', phase: 'result' })
    } catch (err) {
      console.error('capture failed', err)
      await setRobotState('IDLE')
      dispatch({ type: 'SET_ERROR', text: 'Something went wrong — try again!' })
      dispatch({ type: 'SET_CAPTURE_PHASE', phase: 'idle' })
    }
  }

  const runNaming = async () => {
    dispatch({ type: 'SET_ERROR', text: '' })
    dispatch({ type: 'SET_CAPTURE_PHASE', phase: 'naming' })
    const ctrl = new AbortController()
    abortRef.current = ctrl
    try {
      const blob = await captureUtterance({ signal: ctrl.signal })
      const spoken = await sendAudioForTranscript(blob)
      const name = spoken.trim() || 'My Pose'
      dispatch({ type: 'SET_SAVED_NAME', name })
      await saveCurrentPose(name)
      dispatch({ type: 'SET_CAPTURE_PHASE', phase: 'saved' })
    } catch (err) {
      console.error('naming failed', err)
      dispatch({ type: 'SET_ERROR', text: "I didn't catch a name — try again!" })
      dispatch({ type: 'SET_CAPTURE_PHASE', phase: 'result' })
    }
  }

  return (
    <>
      <ConceptHeader index={4} title="Save a Pose" onSkip={onNext} />
      <div className="tut-twocol">
        <SimPanel
          cameraUrl={cameraUrl}
          overlay={
            s.capturePhase === 'countdown' && s.countdown != null ? (
              <div className="tut-capture-countdown">
                <span key={s.countdown}>{s.countdown}</span>
              </div>
            ) : s.capturePhase === 'analyzing' ? (
              <div className="tut-capture-analyzing">
                <div className="tut-checking-spinner" />
                <div className="tut-checking-text">Reading your pose…</div>
              </div>
            ) : null
          }
        />
        <div className="tut-right">
          <div className="tut-right-scroll">
            <AgentBubble>
              {s.captured
                ? 'Nice pose! Now give it a name so you can use it again.'
                : "Let's save a pose. Strike your best pose, hold still, and I'll capture it."}
            </AgentBubble>

            {s.capturePhase === 'idle' && !s.captured && (
              <>
                <div className="tut-capture-heading">Strike a pose! 💪</div>
                <div className="tut-capture-sub">Hold it when the countdown starts.</div>
                <button className="tut-next-btn" onClick={runCapture}>
                  Capture pose ▶
                </button>
              </>
            )}

            {(s.capturePhase === 'result' || s.captured) && (
              <>
                {s.captured?.imageB64 && (
                  <img
                    className="tut-capture-thumb"
                    src={`data:image/jpeg;base64,${s.captured.imageB64}`}
                    alt="Captured pose"
                  />
                )}
                <button className="tut-next-btn" onClick={runNaming}>
                  🎤 Name it with your voice
                </button>
              </>
            )}

            {s.capturePhase === 'naming' && (
              <div className="tut-checking-card">
                <span className="tut-orb-listen-dot" />
                <div className="tut-checking-text">Listening for a name…</div>
              </div>
            )}

            {s.capturePhase === 'saved' && (
              <>
                <div className="tut-success-card">
                  <div className="tut-check-icon">✓</div>
                  <div className="tut-success-text">
                    Saved to My Poses! "{s.savedName}" is in your library.
                  </div>
                </div>
                <button className="tut-next-btn" onClick={onNext}>
                  Got it! Next →
                </button>
              </>
            )}

            {s.error && <div className="tut-waiting-text">{s.error}</div>}
          </div>
        </div>
      </div>
    </>
  )
}

function FreePracticeScreen({
  s,
  dispatch,
  cameraUrl,
  onNext,
  session,
}: {
  s: State
  dispatch: React.Dispatch<Action>
  cameraUrl: string
  onNext: () => void
  session: React.MutableRefObject<ActionSession | null>
}) {
  const abortRef = useRef<AbortController | null>(null)
  const [pendingIntent, setPendingIntent] = useState<IntentResult | null>(null)

  const clear = () => {
    dispatch({ type: 'SET_ERROR', text: '' })
    dispatch({ type: 'SET_TRANSCRIPT', text: '' })
    dispatch({ type: 'CLEAR_STEPPER' })
    setPendingIntent(null)
  }

  const listen = async () => {
    clear()
    dispatch({ type: 'SET_VOICE_PHASE', phase: 'listening' })
    const ctrl = new AbortController()
    abortRef.current = ctrl
    try {
      const blob = await captureUtterance({ signal: ctrl.signal })
      dispatch({ type: 'SET_VOICE_PHASE', phase: 'thinking' })
      const text = await sendAudioForTranscript(blob)
      if (!text.trim()) {
        dispatch({ type: 'SET_ERROR', text: "I didn't catch that — try again!" })
        dispatch({ type: 'SET_VOICE_PHASE', phase: 'idle' })
        return
      }
      dispatch({ type: 'SET_TRANSCRIPT', text })
      dispatch({ type: 'SET_STEPPER', stepper: { command: text } })
      const result = await classifyIntent(text, s.following, undefined, 'tutorial-practice')
      dispatch({ type: 'LOG', text: `practice intent: ${result.type}` })
      dispatch({ type: 'SET_STEPPER', stepper: { understanding: intentDescription(result) } })
      await handleIntent(text, result)
    } catch (err) {
      console.error('free practice failed', err)
      dispatch({ type: 'SET_ERROR', text: 'Something went wrong — try again!' })
      dispatch({ type: 'SET_VOICE_PHASE', phase: 'idle' })
    }
  }

  const handleIntent = async (text: string, result: IntentResult) => {
    if (result.type === 'clarification') {
      dispatch({ type: 'SET_STEPPER', stepper: { clarification: result.question } })
      dispatch({ type: 'SET_VOICE_PHASE', phase: 'idle' })
      return
    }
    if (result.type === 'conversation') {
      dispatch({ type: 'SET_STEPPER', stepper: { safety: { ok: true }, execute: 'Talking with you' } })
      await session.current?.sendText(text, 'conversation')
      dispatch({ type: 'SET_VOICE_PHASE', phase: 'done' })
      dispatch({ type: 'MARK_PRACTICE_READY' })
      return
    }
    if (result.type === 'motion') {
      setPendingIntent(result)
      dispatch({ type: 'SET_STEPPER', stepper: { safety: { ok: true }, execute: 'Waiting for your approval' } })
      dispatch({ type: 'SET_VOICE_PHASE', phase: 'idle' })
      return
    }
    if (result.type === 'immediate') {
      const intent = result.intent
      if (intent === 'follow_start') {
        dispatch({ type: 'SET_FOLLOWING', active: true })
        await session.current?.sendText(text, 'immediate')
        dispatch({ type: 'SET_STEPPER', stepper: { safety: { ok: true }, execute: 'Now following you' } })
      } else if (intent === 'follow_stop') {
        dispatch({ type: 'SET_FOLLOWING', active: false })
        await session.current?.sendText(text, 'immediate')
        dispatch({ type: 'SET_STEPPER', stepper: { safety: { ok: true }, execute: 'Stopped following' } })
      } else if (intent === 'capture') {
        dispatch({ type: 'SET_STEPPER', stepper: { safety: { ok: true }, execute: 'Capture started' } })
        // Simplify: just tell them to use the save concept; or run mini-capture inline.
        await runMiniCapture()
      } else if (intent === 'save_robot_pose' || intent === 'naming') {
        dispatch({ type: 'SET_STEPPER', stepper: { safety: { ok: true }, execute: 'Ready to save current pose' } })
      } else {
        await session.current?.sendText(text, 'immediate')
        dispatch({ type: 'SET_STEPPER', stepper: { safety: { ok: true }, execute: 'Done' } })
      }
      dispatch({ type: 'SET_VOICE_PHASE', phase: 'done' })
      dispatch({ type: 'MARK_PRACTICE_READY' })
    }
  }

  const approveMotion = async () => {
    if (!pendingIntent || pendingIntent.type !== 'motion') return
    dispatch({ type: 'SET_VOICE_PHASE', phase: 'thinking' })
    try {
      await session.current?.sendText(s.transcript, 'motion', pendingIntent.description)
      dispatch({ type: 'SET_STEPPER', stepper: { execute: 'Moved in the simulator' } })
      dispatch({ type: 'SET_VOICE_PHASE', phase: 'done' })
      dispatch({ type: 'MARK_PRACTICE_READY' })
    } catch (err) {
      dispatch({ type: 'SET_ERROR', text: 'Could not run that move.' })
      dispatch({ type: 'SET_VOICE_PHASE', phase: 'idle' })
    }
    setPendingIntent(null)
  }

  const rejectMotion = () => {
    setPendingIntent(null)
    dispatch({ type: 'SET_STEPPER', stepper: { execute: 'Cancelled — try saying it differently' } })
    dispatch({ type: 'SET_VOICE_PHASE', phase: 'idle' })
  }

  const runMiniCapture = async () => {
    dispatch({ type: 'SET_CAPTURE_PHASE', phase: 'countdown' })
    dispatch({ type: 'SET_COUNTDOWN', n: 3 })
    try {
      await setRobotState('DEMO_LOCKED')
      for (const n of [3, 2, 1]) {
        dispatch({ type: 'SET_COUNTDOWN', n })
        await sleep(1000)
      }
      dispatch({ type: 'SET_COUNTDOWN', n: null })
      playShutter()
      const result = await mapFeatures()
      await setRobotState('IDLE')
      if (result.poseDetected) {
        await move(result.commands)
      }
      dispatch({ type: 'SET_CAPTURE_PHASE', phase: 'idle' })
    } catch (err) {
      await setRobotState('IDLE')
      dispatch({ type: 'SET_ERROR', text: 'Capture did not work that time.' })
      dispatch({ type: 'SET_CAPTURE_PHASE', phase: 'idle' })
    }
  }

  useEffect(() => {
    return () => { abortRef.current?.abort() }
  }, [])

  const prompts = [
    'raise your right arm',
    'follow my movement',
    'capture my pose',
    'what can you do?',
  ]

  return (
    <>
      <div className="tut-colheader">
        <div className="tut-colheader-left">
          <div className="tut-logo-box">
            <div className="tut-logo-diamond" />
          </div>
          <span className="tut-badge tut-badge-real">FREE PRACTICE</span>
          <div className="tut-colheader-title">Try anything you learned</div>
        </div>
        <button
          className="tut-skip-btn"
          onClick={onNext}
          style={{ color: s.practiceReady ? 'var(--accent)' : undefined }}
        >
          {s.practiceReady ? "I'm ready →" : 'Skip →'}
        </button>
      </div>

      <div className="tut-twocol">
        <SimPanel
          cameraUrl={cameraUrl}
          overlay={
            s.capturePhase === 'countdown' && s.countdown != null ? (
              <div className="tut-capture-countdown">
                <span key={s.countdown}>{s.countdown}</span>
              </div>
            ) : null
          }
        />
        <div className="tut-right">
          <div className="tut-right-scroll">
            <AgentBubble>
              Now it's your turn! Try a voice command and watch the stepper. When you feel ready, tap "I'm ready."
            </AgentBubble>

            <SuggestedChips prompts={prompts} onPrompt={() => listen()} />
            <MicOrb phase={s.voicePhase} onClick={listen} label="Tap and tell me what to do" />

            <TranscriptBox text={s.transcript} />
            {s.error && <div className="tut-waiting-text">{s.error}</div>}

            {pendingIntent && (
              <div className="tut-intent-card">
                <div className="tut-intent-header">
                  <div className="tut-intent-icon">?</div>
                  <span className="tut-intent-label">APPROVE THIS MOVE?</span>
                </div>
                <div className="tut-intent-text">{intentDescription(pendingIntent)}</div>
                <div className="tut-intent-btns">
                  <button className="tut-btn-primary" onClick={approveMotion}>
                    Yes, do it
                  </button>
                  <button className="tut-btn-ghost" onClick={rejectMotion}>
                    No, cancel
                  </button>
                </div>
              </div>
            )}

            <AIReasoningStepper steps={buildStepperItems(s.stepper)} />

            <button
              className="tut-next-btn"
              onClick={onNext}
              disabled={!s.practiceReady}
              style={{ opacity: !s.practiceReady ? 0.5 : 1 }}
            >
              I'm ready! Meet the real {ROBOT_NAME} →
            </button>
          </div>
        </div>
      </div>
    </>
  )
}

function StageNav({ screen, onJump }: { screen: Screen; onJump: (screen: Screen) => void }) {
  const stages: { label: string; screen: Screen }[] = [
    { label: 'Welcome', screen: 'welcome' },
    { label: 'Playground', screen: 'sim-playground' },
    { label: 'Joints', screen: 'concept-joints' },
    { label: 'Intent', screen: 'concept-intent' },
    { label: 'Safety', screen: 'concept-safety' },
    { label: 'Follow', screen: 'concept-follow' },
    { label: 'Save', screen: 'concept-save' },
    { label: 'Practice', screen: 'free-practice' },
    { label: 'Ready', screen: 'ready' },
  ]
  return (
    <div className="tut-stage-nav">
      <span className="tut-stage-nav-label">Progress</span>
      {stages.map((st) => (
        <button
          key={st.screen}
          className={`tut-stage-btn ${screen === st.screen ? 'tut-stage-btn-active' : ''}`}
          onClick={() => onJump(st.screen)}
        >
          {st.label}
        </button>
      ))}
    </div>
  )
}

function ReadyScreen({ onMeetRobot }: { onMeetRobot: () => void }) {
  return (
    <div className="tut-ready">
      <Confetti />
      <div className="tut-ready-stars">
        <span style={{ fontSize: 26 }}>★</span>
        <span className="tut-ready-title">You did it!</span>
        <span style={{ fontSize: 26 }}>★</span>
      </div>
      <div className="tut-ready-robot">
        <RobotIllustration wave happy />
      </div>
      <div className="tut-ready-msg">
        <div className="tut-ready-msg-title">You taught {ROBOT_NAME} really well in there.</div>
        <div className="tut-ready-msg-sub">Ready to try with the real robot?</div>
      </div>
      <button className="tut-ready-cta" onClick={onMeetRobot}>
        Meet the real {ROBOT_NAME}! →
      </button>
    </div>
  )
}

function FacilitatorOverlay({
  s,
  dispatch,
  onJump,
}: {
  s: State
  dispatch: React.Dispatch<Action>
  onJump: (screen: Screen) => void
}) {
  if (!s.facilitatorOpen) return null
  return (
    <div
      className="tut-mini-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) dispatch({ type: 'TOGGLE_FACILITATOR' })
      }}
    >
      <div className="tut-mini-card" style={{ textAlign: 'left', width: 520 }}>
        <div className="tut-mini-title">Facilitator view</div>
        <div className="tut-mini-sub">Jump to any screen or reset the robot.</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 16 }}>
          {SCREENS.map((sc) => (
            <button
              key={sc}
              className={`tut-switcher-btn ${s.screen === sc ? 'tut-switcher-btn-active' : 'tut-switcher-btn-inactive'}`}
              onClick={() => {
                onJump(sc)
                dispatch({ type: 'TOGGLE_FACILITATOR' })
              }}
            >
              {sc}
            </button>
          ))}
        </div>
        <button
          className="tut-btn-primary"
          onClick={() => {
            resetPose().catch(() => {})
          }}
        >
          Return to stand
        </button>
        <div style={{ marginTop: 16, maxHeight: 160, overflowY: 'auto', fontSize: 12, fontFamily: 'monospace', color: '#666' }}>
          {s.sessionLog.map((line, i) => (
            <div key={i}>{line}</div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ---- Main Component ----

export default function Tutorial() {
  const [s, dispatch] = useReducer(reducer, initState)
  const navigate = useNavigate()
  const actionSessionRef = useRef<ActionSession | null>(null)

  const cameraUrl = getRobotStream() + '/video_feed'

  useEffect(() => {
    actionSessionRef.current = openActionSession('tutorial')
    return () => {
      actionSessionRef.current?.close()
      setRobotState('IDLE').catch(() => {})
    }
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === '?' && !e.ctrlKey && !e.metaKey && !e.altKey) {
        dispatch({ type: 'TOGGLE_FACILITATOR' })
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const go = useCallback((screen: Screen) => {
    dispatch({ type: 'GO', screen })
  }, [])

  const sendCommand = useCallback(async (text: string): Promise<ActionResult> => {
    return actionSessionRef.current!.sendText(text)
  }, [])

  const runBlockMove = useCallback(async (part: string, dir: string) => {
    dispatch({ type: 'BLOCK_CHECKING' })
    try {
      await sendCommand(`${dir} the left ${part}`)
      dispatch({ type: 'BLOCK_CONFIRMED' })
    } catch (err) {
      console.error('block move failed', err)
      dispatch({ type: 'SET_ERROR', text: 'That move did not work — try a different one.' })
      dispatch({ type: 'BLOCK_CHECKING' })
    }
  }, [sendCommand])

  const meetRobot = useCallback(() => {
    navigate('/home', { state: { fromApp: true } })
  }, [navigate])

  return (
    <div className="tut-root">
      {/* Facilitator hint */}
      <button
        className="tut-facilitator-hint"
        onClick={() => dispatch({ type: 'TOGGLE_FACILITATOR' })}
        title="Facilitator view (?)"
      >
        ?
      </button>

      {s.screen === 'welcome' && <WelcomeScreen onStart={() => go('sim-playground')} onSkip={() => go('ready')} />}

      {s.screen === 'sim-playground' && (
        <SimPlaygroundScreen
          s={s}
          dispatch={dispatch}
          cameraUrl={cameraUrl}
          onNext={() => go('concept-joints')}
          runBlockMove={runBlockMove}
        />
      )}

      {s.screen === 'concept-joints' && (
        <ConceptJointsScreen
          s={s}
          dispatch={dispatch}
          cameraUrl={cameraUrl}
          onNext={() => go('concept-intent')}
          sendCommand={sendCommand}
        />
      )}

      {s.screen === 'concept-intent' && (
        <ConceptIntentScreen
          s={s}
          dispatch={dispatch}
          cameraUrl={cameraUrl}
          onNext={() => go('concept-safety')}
          sendCommand={sendCommand}
        />
      )}

      {s.screen === 'concept-safety' && (
        <ConceptSafetyScreen
          s={s}
          dispatch={dispatch}
          cameraUrl={cameraUrl}
          onNext={() => go('concept-follow')}
          sendCommand={sendCommand}
        />
      )}

      {s.screen === 'concept-follow' && (
        <ConceptFollowScreen
          s={s}
          dispatch={dispatch}
          cameraUrl={cameraUrl}
          onNext={() => go('concept-save')}
          session={actionSessionRef}
        />
      )}

      {s.screen === 'concept-save' && (
        <ConceptSaveScreen
          s={s}
          dispatch={dispatch}
          cameraUrl={cameraUrl}
          onNext={() => go('free-practice')}
        />
      )}

      {s.screen === 'free-practice' && (
        <FreePracticeScreen
          s={s}
          dispatch={dispatch}
          cameraUrl={cameraUrl}
          onNext={() => go('ready')}
          session={actionSessionRef}
        />
      )}

      {s.screen === 'ready' && <ReadyScreen onMeetRobot={meetRobot} />}

      <StageNav screen={s.screen} onJump={go} />
      <FacilitatorOverlay s={s} dispatch={dispatch} onJump={go} />
    </div>
  )
}
