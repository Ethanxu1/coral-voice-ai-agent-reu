import { useReducer, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getRobotStream } from '../demo/robotConfig'
import { openActionSession, captureUtterance, sendAudioForTranscript, resetPose, mapFeatures, move, playShutter, saveCurrentPose, setRobotState, sleep, type ActionSession, type ActionResult } from '../demo/api'
import RobotViewer from './RobotViewer'
import './Tutorial.css'

const ROBOT_NAME = 'CORAL'

type Screen = 'welcome' | 'blocks' | 'concept' | 'ready'

interface State {
  screen: Screen
  conceptIdx: number
  blockPart: string | null
  blockDir: string | null
  blockChecking: boolean
  blockConfirmed: boolean
  intentDone: boolean
  safetyDone: boolean
  safetyChecking: boolean
}

type Action =
  | { type: 'GO'; screen: Screen }
  | { type: 'GO_CONCEPT'; idx: number }
  | { type: 'SET_BLOCK_PART'; val: string }
  | { type: 'SET_BLOCK_DIR'; val: string }
  | { type: 'RESET_BLOCKS' }
  | { type: 'BLOCK_CHECKING' }
  | { type: 'BLOCK_CONFIRMED' }
  | { type: 'BLOCK_FAILED' }
  | { type: 'INTENT_DONE' }
  | { type: 'SAFETY_CHECKING' }
  | { type: 'SAFETY_DONE' }

function reducer(s: State, a: Action): State {
  switch (a.type) {
    case 'GO': return { ...s, screen: a.screen, intentDone: false, safetyDone: false, safetyChecking: false, blockChecking: false, blockConfirmed: false }
    case 'GO_CONCEPT': return { ...s, screen: 'concept', conceptIdx: a.idx, intentDone: false, safetyDone: false, safetyChecking: false }
    case 'SET_BLOCK_PART': return { ...s, blockPart: a.val, blockConfirmed: false, blockChecking: false }
    case 'SET_BLOCK_DIR': return { ...s, blockDir: a.val, blockConfirmed: false, blockChecking: false }
    case 'RESET_BLOCKS': return { ...s, blockPart: null, blockDir: null, blockConfirmed: false, blockChecking: false }
    case 'BLOCK_CHECKING': return { ...s, blockChecking: true }
    case 'BLOCK_CONFIRMED': return { ...s, blockChecking: false, blockConfirmed: true }
    case 'BLOCK_FAILED': return { ...s, blockChecking: false, blockConfirmed: false }
    case 'INTENT_DONE': return { ...s, intentDone: true }
    case 'SAFETY_CHECKING': return { ...s, safetyChecking: true }
    case 'SAFETY_DONE': return { ...s, safetyChecking: false, safetyDone: true }
    default: return s
  }
}

const initState: State = {
  screen: 'welcome',
  conceptIdx: 0,
  blockPart: null,
  blockDir: null,
  blockChecking: false,
  blockConfirmed: false,
  intentDone: false,
  safetyDone: false,
  safetyChecking: false,
}

// ---- Robot Illustration ----
function RobotIllustration({ wave = false, happy = false, highlight = '' }: { wave?: boolean; happy?: boolean; highlight?: string }) {
  const hotLeft = highlight === 'leftArm'
  const hotRight = highlight === 'rightArm'
  const hotCore = highlight === 'core'
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
        {hotCore && <div className="tut-robot-torso-glow" />}
        {/* left arm */}
        <div className={`tut-robot-arm tut-robot-arm-left${wave ? ' tut-robot-arm-wave' : ''}`}>
          <div className="tut-robot-joint">
            {hotLeft && <div className="tut-robot-joint-glow" />}
          </div>
          <div className={`tut-robot-limb${hotLeft ? ' tut-robot-limb-hot' : ''}`} />
        </div>
        {/* right arm */}
        <div className="tut-robot-arm tut-robot-arm-right">
          <div className="tut-robot-joint">
            {hotRight && <div className="tut-robot-joint-glow" />}
          </div>
          <div className={`tut-robot-limb${hotRight ? ' tut-robot-limb-hot' : ''}`} />
        </div>
      </div>
      <div className="tut-robot-legs">
        <div className="tut-robot-leg" />
        <div className="tut-robot-leg" />
      </div>
    </div>
  )
}

// ---- Sim Placeholder ----
function SimPanel({ badge = 'SIM', safetyColor = '#3FA76B', safetyLabel = 'Safe zone', caption = '', cameraUrl }: {
  badge?: string; safetyColor?: string; safetyLabel?: string; caption?: string; cameraUrl?: string
}) {
  // Track whether the camera feed is actually rendering. The placeholder
  // icon/label should only show when the feed is unavailable.
  const [feedReady, setFeedReady] = useState(false)
  useEffect(() => { setFeedReady(false) }, [cameraUrl])

  return (
    <div className="tut-sim">
      <div className="tut-sim-grid" />
      <div className="tut-sim-vignette" />
      <div className="tut-sim-floor" />
      <div className="tut-sim-badge-top">
        <span className="tut-sim-badge-dot" />
        {badge}
      </div>
      <div className="tut-sim-safety">
        <span style={{ width: 10, height: 10, borderRadius: '50%', background: safetyColor, boxShadow: `0 0 10px ${safetyColor}`, display: 'inline-block' }} />
        {safetyLabel}
      </div>
      <RobotViewer embedded />
      {caption && (
        <div className="tut-sim-caption">
          <div className="tut-sim-caption-pill">{caption}</div>
        </div>
      )}
      <div className="tut-pip">
        {cameraUrl && (
          <img
            src={cameraUrl}
            style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover', borderRadius: 14 }}
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

const CONCEPTS = [
  {
    no: '1', title: 'Joints & Movement', demo: 'joints', highlight: 'rightArm',
    script: `You can also use your voice to control me!`,
    transcript: 'raise your right arm',
  },
  {
    no: '2', title: 'Instructions & Intent', demo: 'intent', highlight: 'leftArm',
    script: `When you talk to me, I make my best guess about what you mean. Say a move and watch what I think you want.`,
    transcript: 'move the arm up',
  },
  {
    no: '3', title: 'Safety Checks', demo: 'safety', highlight: 'core',
    script: `I always check a move is safe before I try it. First I'll stand back up — then ask me to rotate my right arm all the way into my stomach and watch what happens.`,
    transcript: 'rotate the right arm all the way into stomach',
  },
  {
    no: '4', title: 'Saving a Pose', demo: 'save', highlight: 'rightArm',
    script: `See that little camera feed in the corner? That's how I see you — let me show you what I actually look for.`,
    transcript: 'save this pose',
  },
]

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
        <div key={i} className="tut-confetti-bit" style={{ left: b.left, width: b.width, height: b.height, background: b.background, animationDuration: b.animationDuration, animationDelay: b.animationDelay, animationFillMode: b.animationFillMode }} />
      ))}
    </div>
  )
}

// ---- Stage Navigator ----
function StageNav({ s, go, goConcept, navigate }: { s: State; go: (screen: Screen) => void; goConcept: (i: number) => void; navigate: (path: string, opts?: { state?: unknown }) => void }) {
  const stages = [
    { label: 'Welcome', isActive: s.screen === 'welcome', onClick: () => go('welcome') },
    { label: 'Explore', isActive: s.screen === 'blocks', onClick: () => go('blocks') },
    { label: 'Joints', isActive: s.screen === 'concept' && s.conceptIdx === 0, onClick: () => goConcept(0) },
    { label: 'Intent', isActive: s.screen === 'concept' && s.conceptIdx === 1, onClick: () => goConcept(1) },
    { label: 'Safety', isActive: s.screen === 'concept' && s.conceptIdx === 2, onClick: () => goConcept(2) },
    { label: 'Save', isActive: s.screen === 'concept' && s.conceptIdx === 3, onClick: () => goConcept(3) },
    { label: 'Ready', isActive: s.screen === 'ready', onClick: () => go('ready') },
    { label: 'Real robot', isActive: false, onClick: () => navigate('/home', { state: { fromApp: true } }) },
  ]
  return (
    <div className="tut-stage-nav">
      <span className="tut-stage-nav-label">SCREENS</span>
      {stages.map((st, i) => (
        <button key={i} className={`tut-stage-btn${st.isActive ? ' tut-stage-btn-active' : ''}`} onClick={st.onClick}>
          {i + 1} · {st.label}
        </button>
      ))}
    </div>
  )
}

// ---- Main Component ----
export default function Tutorial() {
  const [s, dispatch] = useReducer(reducer, initState)
  const navigate = useNavigate()
  const actionSessionRef = useRef<ActionSession | null>(null)

  const go = (screen: Screen) => dispatch({ type: 'GO', screen })
  const goConcept = (idx: number) => dispatch({ type: 'GO_CONCEPT', idx })
  const nextConcept = () => {
    if (s.conceptIdx < 3) goConcept(s.conceptIdx + 1)
    else go('ready')
  }
  const cameraUrl = getRobotStream() + '/video_feed'

  // Shared with the Joints/Safety voice demos and the Explore "Confirm & simulate"
  // block: sends a command to the real LLM motion planner over the same /ws
  // pipeline the guided demo uses, so the sim actually performs the move.
  useEffect(() => {
    return () => { actionSessionRef.current?.close() }
  }, [])

  const sendCommand = async (text: string): Promise<ActionResult> => {
    if (!actionSessionRef.current) {
      actionSessionRef.current = openActionSession()
    }
    return actionSessionRef.current.sendText(text)
  }

  // We always say "left" — the block picker only lets you choose a part, not
  // a side.
  const runBlockMove = async (part: string, dir: string) => {
    dispatch({ type: 'BLOCK_CHECKING' })
    try {
      await sendCommand(`${dir} the left ${part}`)
      dispatch({ type: 'BLOCK_CONFIRMED' })
    } catch (err) {
      console.error('block move failed', err)
      dispatch({ type: 'BLOCK_FAILED' })
    }
  }

  const cc = CONCEPTS[s.conceptIdx] || CONCEPTS[0]
  const safetyColor = s.screen === 'concept' && cc.demo === 'safety' && !s.safetyDone
    ? '#EF6560'
    : s.screen === 'concept' && cc.demo === 'intent' ? '#F0A93A'
    : '#3FA76B'
  const safetyLabel = safetyColor === '#EF6560' ? 'Too close!' : safetyColor === '#F0A93A' ? 'Getting near' : 'Safe zone'

  const isConcept = s.screen === 'concept'
  const isBlocks = s.screen === 'blocks'

  const dots = [0, 1, 2, 3].map(i =>
    i === s.conceptIdx ? 'tut-dot-active' : i < s.conceptIdx ? 'tut-dot-done' : 'tut-dot-upcoming'
  )

  const simCaption = isBlocks && s.blockPart && s.blockDir ? `Simulating: ${s.blockDir} ${s.blockPart}` : ''

  return (
    <div className="tut-root">
      {/* Always-available: snap the sim robot back to a standing pose. */}
      <button className="tut-return-stand" onClick={() => { resetPose().catch(() => {}) }}>
        Return to stand
      </button>

      {/* WELCOME */}
      {s.screen === 'welcome' && (
        <div className="tut-welcome">
          <div className="tut-welcome-grid" />
          <div className="tut-welcome-logo">
            <div className="tut-logo-box"><div className="tut-logo-diamond" /></div>
            <div><div className="tut-logo-name">{ROBOT_NAME}</div><div className="tut-logo-sub">TUTORIAL</div></div>
          </div>
          <div className="tut-welcome-robot">
            <RobotIllustration />
          </div>
          <div className="tut-welcome-bubble">
            <div className="tut-welcome-title">Hey! I'm {ROBOT_NAME}'s helper. Today, <span style={{ color: 'var(--accent)' }}>YOU</span> get to be the robot teacher.</div>
            <div className="tut-welcome-sub">Before we meet the real robot, let's practice in here first. Ready?</div>
          </div>
          <div className="tut-welcome-btns">
            <button className="tut-welcome-cta" onClick={() => go('blocks')}>Let's go!</button>
            <button className="tut-welcome-skip" onClick={() => go('ready')}>Skip →</button>
          </div>
        </div>
      )}

      {/* READY */}
      {s.screen === 'ready' && (
        <div className="tut-ready">
          <Confetti />
          <div className="tut-ready-stars">
            <span style={{ fontSize: 26 }}>★</span>
            <span className="tut-ready-title">You did it!</span>
            <span style={{ fontSize: 26 }}>★</span>
          </div>
          <div className="tut-ready-robot"><RobotIllustration wave happy /></div>
          <div className="tut-ready-msg">
            <div className="tut-ready-msg-title">You taught {ROBOT_NAME} really well in there.</div>
            <div className="tut-ready-msg-sub">Ready to try with the real robot?</div>
          </div>
          <button className="tut-ready-cta" onClick={() => navigate('/home', { state: { fromApp: true } })}>
            Meet the real {ROBOT_NAME}! →
          </button>
        </div>
      )}

      {/* TWO-COL SCREENS */}
      {s.screen !== 'welcome' && s.screen !== 'ready' && (
        <>
          {/* Context bar */}
          <div className="tut-colheader">
            <div className="tut-colheader-left">
              <div className="tut-logo-box"><div className="tut-logo-diamond" /></div>
              {isConcept && (
                <>
                  <div className="tut-dots">{dots.map((cls, i) => <span key={i} className={cls} />)}</div>
                  <div className="tut-colheader-title">Concept {cc.no} of 4 · {cc.title}</div>
                </>
              )}
              {isBlocks && (
                <>
                  <span className="tut-badge tut-badge-explore">EXPLORE</span>
                  <div className="tut-colheader-title">Build a move, block by block</div>
                </>
              )}
            </div>
            <button className="tut-skip-btn" onClick={() => go('ready')}>Skip →</button>
          </div>

          <div className="tut-twocol">
            <SimPanel
              badge="SIM"
              safetyColor={safetyColor}
              safetyLabel={safetyLabel}
              caption={simCaption}
              cameraUrl={cameraUrl}
            />
            <div className="tut-right">
              {isConcept && <ConceptPanel s={s} dispatch={dispatch} cc={cc} nextConcept={nextConcept} sendCommand={sendCommand} />}
              {isBlocks && <BlocksPanel s={s} dispatch={dispatch} goConcept={goConcept} runBlockMove={runBlockMove} />}
            </div>
          </div>
        </>
      )}

      {/* Stage navigator - shown on all screens */}
      <StageNav s={s} go={go} goConcept={goConcept} navigate={navigate} />
    </div>
  )
}

// ---- Joints voice demo: real mic capture → transcript → LLM motion planner ----
type VoicePhase = 'idle' | 'listening' | 'thinking' | 'done' | 'error'

function JointsVoiceDemo({ prompt, sendCommand, nextConcept }: { prompt: string; sendCommand: (text: string) => Promise<ActionResult>; nextConcept: () => void }) {
  const [phase, setPhase] = useState<VoicePhase>('idle')
  const [heard, setHeard] = useState('')
  const [error, setError] = useState('')
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    return () => { abortRef.current?.abort() }
  }, [])

  const startListening = async () => {
    setError('')
    setHeard('')
    setPhase('listening')
    const ctrl = new AbortController()
    abortRef.current = ctrl
    try {
      const blob = await captureUtterance({ signal: ctrl.signal })
      setPhase('thinking')
      const text = await sendAudioForTranscript(blob)
      if (!text.trim()) {
        setError("I didn't catch that — try again!")
        setPhase('idle')
        return
      }
      setHeard(text)
      await sendCommand(text)
      setPhase('done')
    } catch (err) {
      console.error('joints voice demo failed', err)
      setError("Something went wrong — try again!")
      setPhase('idle')
    }
  }

  return (
    <>
      <div className="tut-mic-wrap">
        <div className="tut-orb-container">
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
        {phase === 'idle' && (
          <button className="tut-next-btn" onClick={startListening}>🎤 Tap and say "{prompt}"</button>
        )}
        {phase === 'listening' && (
          <div className="tut-orb-listen-label">
            <span className="tut-orb-listen-dot" />
            Listening… say "{prompt}"
          </div>
        )}
        {phase === 'thinking' && (
          <div className="tut-orb-listen-label">Thinking…</div>
        )}
        {heard && (
          <div className="tut-transcript">
            <div className="tut-transcript-label">YOU SAID</div>
            <div className="tut-transcript-text">"{heard}"</div>
          </div>
        )}
        {error && <div className="tut-waiting-text">{error}</div>}
      </div>
      {phase === 'done' && (
        <button className="tut-next-btn" onClick={nextConcept}>Got it! Next →</button>
      )}
    </>
  )
}

// ---- Safety voice demo: stand → real voice command → collision-checker explainer ----
type SafetyPhase = 'resetting' | 'ready' | 'listening' | 'thinking' | 'done' | 'error'

function SafetyVoiceDemo({ prompt, sendCommand, dispatch, safetyDone, nextConcept }: {
  prompt: string
  sendCommand: (text: string) => Promise<ActionResult>
  dispatch: React.Dispatch<Action>
  safetyDone: boolean
  nextConcept: () => void
}) {
  const [phase, setPhase] = useState<SafetyPhase>('resetting')
  const [heard, setHeard] = useState('')
  const [error, setError] = useState('')
  const abortRef = useRef<AbortController | null>(null)
  const didReset = useRef(false)

  // Step 1: stand the robot back up before asking for the risky move, so the
  // "before" state is consistent every time this step is replayed.
  useEffect(() => {
    if (didReset.current) return
    didReset.current = true
    resetPose()
      .catch((err) => console.error('reset pose failed', err))
      .finally(() => setPhase('ready'))
    return () => { abortRef.current?.abort() }
  }, [])

  const startListening = async () => {
    setError('')
    setHeard('')
    setPhase('listening')
    dispatch({ type: 'SAFETY_CHECKING' })
    const ctrl = new AbortController()
    abortRef.current = ctrl
    try {
      // Step 2: record the child actually saying the command.
      const blob = await captureUtterance({ signal: ctrl.signal })
      setPhase('thinking')
      const text = await sendAudioForTranscript(blob)
      if (!text.trim()) {
        setError("I didn't catch that — try again!")
        setPhase('ready')
        return
      }
      setHeard(text)
      // Step 3: send the recorded prompt to the real motion-planner
      // controller. The backend's CollisionChecker runs on every waypoint,
      // so the arm will stop short instead of colliding with the torso.
      await sendCommand(text)
      setPhase('done')
      dispatch({ type: 'SAFETY_DONE' })
    } catch (err) {
      console.error('safety voice demo failed', err)
      setError('Something went wrong — try again!')
      setPhase('ready')
    }
  }

  return (
    <>
      {phase === 'resetting' && (
        <div className="tut-checking-card">
          <div className="tut-checking-spinner" />
          <div className="tut-checking-text">Standing {ROBOT_NAME} back up…</div>
        </div>
      )}

      {phase !== 'resetting' && (
        <div className="tut-mic-wrap">
          <div className="tut-orb-container">
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
          {phase === 'ready' && (
            <button className="tut-next-btn" onClick={startListening}>🎤 Tap and say "{prompt}"</button>
          )}
          {phase === 'listening' && (
            <div className="tut-orb-listen-label">
              <span className="tut-orb-listen-dot" />
              Listening… say "{prompt}"
            </div>
          )}
          {phase === 'thinking' && <div className="tut-orb-listen-label">Thinking…</div>}
          {heard && (
            <div className="tut-transcript">
              <div className="tut-transcript-label">YOU SAID</div>
              <div className="tut-transcript-text">"{heard}"</div>
            </div>
          )}
          {error && <div className="tut-waiting-text">{error}</div>}
        </div>
      )}

      {phase === 'done' && safetyDone && (
        <>
          <div className="tut-success-card">
            <div className="tut-check-icon">✓</div>
            <div className="tut-success-text">
              See that? {ROBOT_NAME}'s arm stopped just short instead of crashing into its own stomach.
            </div>
          </div>
          <div className="tut-intent-tip">
            <span className="tut-intent-tip-dot" />
            Before every move, the simulator runs a collision checker that catches this and backs the motion off automatically — so nobody gets hurt.
          </div>
          <button className="tut-next-btn" onClick={nextConcept}>Got it! Next →</button>
        </>
      )}
    </>
  )
}

// ---- Concept Panel ----
function ConceptPanel({ s, dispatch, cc, nextConcept, sendCommand }: { s: State; dispatch: React.Dispatch<Action>; cc: typeof CONCEPTS[0]; nextConcept: () => void; sendCommand: (text: string) => Promise<ActionResult> }) {
  const isJoints = cc.demo === 'joints'
  const isIntent = cc.demo === 'intent'
  const isSafety = cc.demo === 'safety'
  const isSave = cc.demo === 'save'

  return (
    <div className="tut-right-scroll">
      <div className="tut-agent-bubble">
        <div className="tut-agent-header">
          <span className="tut-agent-dot" />
          <span className="tut-agent-name">{ROBOT_NAME}'S HELPER</span>
        </div>
        <div className="tut-agent-script">{cc.script}</div>
      </div>

      {/* JOINTS */}
      {isJoints && (
        <JointsVoiceDemo prompt={cc.transcript} sendCommand={sendCommand} nextConcept={nextConcept} />
      )}

      {/* INTENT */}
      {isIntent && (
        <>
          <div className="tut-transcript">
            <div className="tut-transcript-label">YOU SAID</div>
            <div className="tut-transcript-text">"{cc.transcript}"</div>
          </div>
          {!s.intentDone ? (
            <>
              <div className="tut-intent-card">
                <div className="tut-intent-header">
                  <div className="tut-intent-icon">?</div>
                  <span className="tut-intent-label">MY BEST GUESS</span>
                </div>
                <div className="tut-intent-text">
                  I think you want to raise {ROBOT_NAME}'s <span style={{ color: 'var(--accent)', fontWeight: 800 }}>LEFT ARM</span>. Is that right?
                </div>
                <div className="tut-intent-btns">
                  <button className="tut-btn-primary" onClick={() => dispatch({ type: 'INTENT_DONE' })}>Yes, that's it</button>
                  <button className="tut-btn-ghost" onClick={() => dispatch({ type: 'INTENT_DONE' })}>No, let me fix it</button>
                </div>
              </div>
              <div className="tut-intent-tip">
                <span className="tut-intent-tip-dot" />
                I'm making a guess — I can't read your mind! You can always correct me.
              </div>
            </>
          ) : (
            <>
              <div className="tut-success-card">
                <div className="tut-check-icon">✓</div>
                <div className="tut-success-text">Nice — you told me exactly what you meant!</div>
              </div>
              <button className="tut-next-btn" onClick={nextConcept}>Got it! Next →</button>
            </>
          )}
        </>
      )}

      {/* SAFETY */}
      {isSafety && (
        <SafetyVoiceDemo
          prompt={cc.transcript}
          sendCommand={sendCommand}
          dispatch={dispatch}
          safetyDone={s.safetyDone}
          nextConcept={nextConcept}
        />
      )}

      {/* SAVE */}
      {isSave && (
        <>
          <div className="tut-intent-card">
            <div className="tut-intent-header">
              <div className="tut-intent-icon">👁</div>
              <span className="tut-intent-label">HOW THE CAMERA SEES YOU</span>
            </div>
            <div className="tut-intent-text">
              That live camera feed in the corner isn't just for show — a computer vision model scans every frame and finds key points on your body: shoulders, elbows, wrists, hips, and knees.
            </div>
          </div>
          <SaveCaptureDemo nextConcept={nextConcept} />
        </>
      )}
    </div>
  )
}

// ---- Blocks Panel ----
function BlocksPanel({ s, dispatch, goConcept, runBlockMove }: { s: State; dispatch: React.Dispatch<Action>; goConcept: (i: number) => void; runBlockMove: (part: string, dir: string) => void }) {
  const bothSet = !!s.blockPart && !!s.blockDir
  const moveText = bothSet ? `${s.blockDir} ${s.blockPart}` : ''

  const partOptions = ['Shoulder', 'Elbow', 'Wrist', 'Hip']
  const dirOptions = ['Raise', 'Lower', 'Extend', 'Bend']

  // Show a brief intro before the block inputs appear, so the child
  // understands the panel is a simulator standing in for the real robot.
  const [showIntro, setShowIntro] = useState(true)

  if (showIntro) {
    return (
      <div className="tut-agent-bubble">
        <div className="tut-agent-header">
          <span className="tut-agent-dot" />
          <span className="tut-agent-name">{ROBOT_NAME}'S HELPER</span>
        </div>
        <div className="tut-agent-script">
          This is a simulator — it moves just like the real {ROBOT_NAME} would, so you can practice safely before we try it on the actual robot.
        </div>
        <button className="tut-next-btn" onClick={() => setShowIntro(false)}>Got it! Next →</button>
      </div>
    )
  }

  return (
    <>
      <div className="tut-blocks-header">
        <div className="tut-blocks-title">Try moving {ROBOT_NAME} yourself</div>
      </div>
      <div className="tut-blocks-body">
        {/* Block 1 */}
        <div className={`tut-block-row ${s.blockPart ? 'tut-block-row-done' : 'tut-block-row-active'}`}>
          <div className="tut-block-inner">
            <div className={`tut-block-num ${s.blockPart ? 'tut-block-num-done' : 'tut-block-num-active'}`}>1</div>
            <div style={{ flex: 1 }}>
              <div className={`tut-block-label tut-block-label-on`}>Pick a body part</div>
              <div className="tut-block-req">Needs: which joint</div>
            </div>
            {s.blockPart && <div className="tut-block-value">{s.blockPart}</div>}
          </div>
          <div className="tut-chips">
            {partOptions.map(o => (
              <button key={o} className={`tut-chip ${s.blockPart === o ? 'tut-chip-sel' : 'tut-chip-unsel'}`} onClick={() => dispatch({ type: 'SET_BLOCK_PART', val: o })}>{o}</button>
            ))}
          </div>
        </div>

        {/* Block 2 */}
        <div className={`tut-block-row ${!s.blockPart ? 'tut-block-row-waiting' : s.blockDir ? 'tut-block-row-done' : 'tut-block-row-active'}`}>
          <div className="tut-block-inner">
            <div className={`tut-block-num ${!s.blockPart ? 'tut-block-num-waiting' : s.blockDir ? 'tut-block-num-done' : 'tut-block-num-active'}`}>2</div>
            <div style={{ flex: 1 }}>
              <div className={`tut-block-label ${s.blockPart ? 'tut-block-label-on' : 'tut-block-label-off'}`}>Set a direction</div>
              <div className="tut-block-req">Needs: which way</div>
            </div>
            {s.blockDir && <div className="tut-block-value">{s.blockDir}</div>}
          </div>
          {s.blockPart && (
            <div className="tut-chips">
              {dirOptions.map(o => (
                <button key={o} className={`tut-chip ${s.blockDir === o ? 'tut-chip-sel' : 'tut-chip-unsel'}`} onClick={() => dispatch({ type: 'SET_BLOCK_DIR', val: o })}>{o}</button>
              ))}
            </div>
          )}
          {!s.blockPart && <div className="tut-waiting-text">Finish the blocks above first.</div>}
        </div>

        {/* Block 3 - confirm */}
        <div className={`tut-block-row ${!bothSet ? 'tut-block-row-waiting' : 'tut-block-row-active'}`}>
          <div className="tut-block-inner">
            <div className={`tut-block-num ${bothSet ? 'tut-block-num-active' : 'tut-block-num-waiting'}`}>3</div>
            <div style={{ flex: 1 }}>
              <div className={`tut-block-label ${bothSet ? 'tut-block-label-on' : 'tut-block-label-off'}`}>Confirm & simulate</div>
            </div>
          </div>
          {bothSet && !s.blockChecking && !s.blockConfirmed && (
            <div className="tut-confirm-btns" style={{ marginTop: 13 }}>
              <button className="tut-btn-primary" style={{ flex: 1 }} onClick={() => runBlockMove(s.blockPart!, s.blockDir!)}>Execute motion</button>
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
                <div className="tut-confirm-text"><strong>{moveText}</strong> completed</div>
              </div>
              <div className="tut-confirm-btns">
                <button className="tut-btn-primary" style={{ flex: 1 }} onClick={() => goConcept(0)}>Continue →</button>
                <button className="tut-btn-ghost" onClick={() => dispatch({ type: 'RESET_BLOCKS' })}>Another</button>
              </div>
            </>
          )}
          {!bothSet && <div className="tut-waiting-text">Finish the blocks above first.</div>}
        </div>
      </div>
    </>
  )
}

// ---- Save concept: inline pose capture ----
// The tutorial's version of the ProDemo capture flow, rendered inline in the
// right panel (no popup): suggest a "Muscles" pose, run a real countdown, snap
// the frame via map-features, drive the sim so the robot mimics the child,
// then let them name the pose with their voice and save it to My Poses. The
// live camera + robot are the page's existing SimPanel / RobotViewer.
const CAPTURE_POSE = 'Muscles'
const MAX_CAPTURE_RETAKES = 3

type CapturePhase = 'intro' | 'countdown' | 'analyzing' | 'retake' | 'result' | 'naming' | 'saving' | 'saved'

function SaveCaptureDemo({ nextConcept }: { nextConcept: () => void }) {
  const [phase, setPhase] = useState<CapturePhase>('intro')
  const [countdown, setCountdown] = useState<number | null>(null)
  const [frame, setFrame] = useState<string | null>(null)
  const [detail, setDetail] = useState('')
  const [error, setError] = useState('')
  const [savedName, setSavedName] = useState(CAPTURE_POSE)
  const tokenRef = useRef(0)
  const captureAbortRef = useRef<AbortController | null>(null)

  // Cancel any in-flight capture/naming (and unlock the robot) on unmount.
  useEffect(() => {
    return () => {
      tokenRef.current++
      captureAbortRef.current?.abort()
      setRobotState('IDLE')
    }
  }, [])

  const runCapture = async () => {
    const token = ++tokenRef.current
    const cancelled = () => tokenRef.current !== token
    setError('')
    setDetail('')

    try {
      for (let take = 0; take < MAX_CAPTURE_RETAKES; take++) {
        // Countdown — hold the pose.
        await setRobotState('DEMO_LOCKED')
        if (cancelled()) return
        setPhase('countdown')
        for (const n of [3, 2, 1]) {
          setCountdown(n)
          await sleep(1000)
          if (cancelled()) return
        }
        setCountdown(null)

        // Snap + retarget the pose to the robot's joints.
        setPhase('analyzing')
        playShutter()
        const result = await mapFeatures()
        if (cancelled()) return

        if (result.poseDetected) {
          setFrame(result.imageB64)
          // Drive the sim so the robot copies the captured pose.
          await move(result.commands).catch(() => {})
          if (cancelled()) return
          await setRobotState('IDLE')
          setPhase('result')
          return
        }

        // No full-body pose — show why and loop for another take.
        setDetail(result.detail || "I couldn't see your whole body — step back so I can see your hips!")
        setPhase('retake')
        await sleep(2200)
        if (cancelled()) return
      }
      // Exhausted retakes.
      await setRobotState('IDLE')
      setError("I couldn't get a clear pose that time. Let's move on!")
      setPhase('intro')
    } catch (err) {
      if (cancelled()) return
      console.error('pose capture failed', err)
      await setRobotState('IDLE')
      setError('Something went wrong — try again!')
      setPhase('intro')
    }
  }

  const runNaming = async () => {
    const token = tokenRef.current
    const cancelled = () => tokenRef.current !== token
    setError('')
    setPhase('naming')
    const ctrl = new AbortController()
    captureAbortRef.current = ctrl
    try {
      // Record the child saying a name, transcribe it, and fall back to the
      // suggested "Muscles" if we couldn't make out anything.
      const blob = await captureUtterance({ signal: ctrl.signal })
      if (cancelled()) return
      const spoken = await sendAudioForTranscript(blob)
      if (cancelled()) return
      const name = spoken.trim() || CAPTURE_POSE
      setSavedName(name)
      setPhase('saving')
      await saveCurrentPose(name)
      if (cancelled()) return
      setPhase('saved')
    } catch (err) {
      if (cancelled()) return
      console.error('pose naming/save failed', err)
      setError("I didn't catch a name — tap to try again!")
      setPhase('result')
    }
  }

  return (
    <div className="tut-capture-inline">
      {phase === 'intro' && (
        <>
          <div className="tut-capture-heading">Strike a "{CAPTURE_POSE}" pose! 💪</div>
          <div className="tut-capture-sub">
            Flex both arms like a strongman — bend your elbows and raise your fists. Hold it when the countdown starts!
          </div>
        </>
      )}
      {phase === 'result' && (
        <>
          <div className="tut-capture-heading">Nice pose! 💪</div>
          <div className="tut-capture-sub">{ROBOT_NAME} matched it using the joints it has. Now give it a name!</div>
        </>
      )}
      {(phase === 'naming' || phase === 'saving') && (
        <>
          <div className="tut-capture-heading">What should we call it?</div>
          <div className="tut-capture-sub">{phase === 'saving' ? 'Saving…' : 'Listening — say a name out loud!'}</div>
        </>
      )}

      {phase === 'countdown' && countdown != null && (
        <div className="tut-capture-stage"><div className="tut-capture-countdown"><span key={countdown}>{countdown}</span></div></div>
      )}
      {phase === 'analyzing' && (
        <div className="tut-checking-card">
          <div className="tut-checking-spinner" />
          <div className="tut-checking-text">Reading your pose…</div>
        </div>
      )}
      {phase === 'retake' && (
        <div className="tut-checking-card">
          <div className="tut-checking-text">{detail}</div>
        </div>
      )}
      {phase === 'naming' && (
        <div className="tut-checking-card">
          <span className="tut-orb-listen-dot" />
          <div className="tut-checking-text">Listening…</div>
        </div>
      )}
      {phase === 'saving' && (
        <div className="tut-checking-card">
          <div className="tut-checking-spinner" />
          <div className="tut-checking-text">Saving "{savedName}"…</div>
        </div>
      )}
      {phase === 'result' && frame && (
        <div className="tut-capture-stage">
          <img className="tut-capture-frame" src={`data:image/jpeg;base64,${frame}`} alt="Captured pose" />
        </div>
      )}
      {phase === 'saved' && (
        <div className="tut-success-card">
          <div className="tut-check-icon">✓</div>
          <div className="tut-success-text">Saved to My Poses! "{savedName}" is in your library — {ROBOT_NAME} can strike it any time.</div>
        </div>
      )}

      {error && <div className="tut-waiting-text">{error}</div>}

      {phase === 'intro' && (
        <button className="tut-next-btn" onClick={runCapture}>Capture pose ▶</button>
      )}
      {phase === 'result' && (
        <button className="tut-next-btn" onClick={runNaming}>🎤 Name it with your voice</button>
      )}
      {phase === 'saved' && (
        <button className="tut-next-btn" onClick={nextConcept}>Got it! Next →</button>
      )}
    </div>
  )
}
