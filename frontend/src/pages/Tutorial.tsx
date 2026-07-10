import { useReducer, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getRobotStream } from '../demo/robotConfig'
import './Tutorial.css'

const ROBOT_NAME = 'CORAL'

type Screen = 'welcome' | 'blocks' | 'concept' | 'playground' | 'ready'
type PlayStep = 'understanding' | 'safepass' | 'blocked'

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
  playStep: PlayStep
  miniOpen: boolean
  miniShots: number
  miniPicked: number | null
}

type Action =
  | { type: 'GO'; screen: Screen }
  | { type: 'GO_CONCEPT'; idx: number }
  | { type: 'SET_BLOCK_PART'; val: string }
  | { type: 'SET_BLOCK_DIR'; val: string }
  | { type: 'RESET_BLOCKS' }
  | { type: 'BLOCK_CHECKING' }
  | { type: 'BLOCK_CONFIRMED' }
  | { type: 'INTENT_DONE' }
  | { type: 'SAFETY_CHECKING' }
  | { type: 'SAFETY_DONE' }
  | { type: 'SET_PLAY'; step: PlayStep }
  | { type: 'OPEN_MINI' }
  | { type: 'MINI_CAPTURE' }
  | { type: 'MINI_PICK'; idx: number }
  | { type: 'MINI_SAVE' }

function reducer(s: State, a: Action): State {
  switch (a.type) {
    case 'GO': return { ...s, screen: a.screen, miniOpen: false, intentDone: false, safetyDone: false, safetyChecking: false, blockChecking: false, blockConfirmed: false }
    case 'GO_CONCEPT': return { ...s, screen: 'concept', conceptIdx: a.idx, miniOpen: false, intentDone: false, safetyDone: false, safetyChecking: false }
    case 'SET_BLOCK_PART': return { ...s, blockPart: a.val, blockConfirmed: false, blockChecking: false }
    case 'SET_BLOCK_DIR': return { ...s, blockDir: a.val, blockConfirmed: false, blockChecking: false }
    case 'RESET_BLOCKS': return { ...s, blockPart: null, blockDir: null, blockConfirmed: false, blockChecking: false }
    case 'BLOCK_CHECKING': return { ...s, blockChecking: true }
    case 'BLOCK_CONFIRMED': return { ...s, blockChecking: false, blockConfirmed: true }
    case 'INTENT_DONE': return { ...s, intentDone: true }
    case 'SAFETY_CHECKING': return { ...s, safetyChecking: true }
    case 'SAFETY_DONE': return { ...s, safetyChecking: false, safetyDone: true }
    case 'SET_PLAY': return { ...s, playStep: a.step }
    case 'OPEN_MINI': return { ...s, miniOpen: true, miniShots: 0, miniPicked: null }
    case 'MINI_CAPTURE': return { ...s, miniShots: Math.min(s.miniShots + 1, 3) }
    case 'MINI_PICK': return { ...s, miniPicked: a.idx }
    case 'MINI_SAVE': return { ...s, miniOpen: false, screen: 'playground' }
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
  playStep: 'understanding',
  miniOpen: false,
  miniShots: 0,
  miniPicked: null,
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
function SimPanel({ badge = 'SIM', safetyColor = '#3FA76B', safetyLabel = 'Safe zone', caption = '', highlight = '', cameraUrl }: {
  badge?: string; safetyColor?: string; safetyLabel?: string; caption?: string; highlight?: string; cameraUrl?: string
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
      <RobotIllustration highlight={highlight} />
      {caption && (
        <div className="tut-sim-caption">
          <div className="tut-sim-caption-pill">{caption}</div>
        </div>
      )}
      {!caption && <div className="tut-sim-label">[ MuJoCo joint simulation ]</div>}
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
    script: `Robots only bend where they have joints — just like your elbow! Try telling ${ROBOT_NAME} to raise its right arm.`,
    transcript: 'raise the right arm',
  },
  {
    no: '2', title: 'Instructions & Intent', demo: 'intent', highlight: 'leftArm',
    script: `When you talk to me, I make my best guess about what you mean. Say a move and watch what I think you want.`,
    transcript: 'move the arm up',
  },
  {
    no: '3', title: 'Safety Checks', demo: 'safety', highlight: 'core',
    script: `I always check a move is safe before ${ROBOT_NAME} tries it. Ask for a really big bend and see what happens!`,
    transcript: 'bend the elbow all the way back',
  },
  {
    no: '4', title: 'Saving a Pose', demo: 'save', highlight: 'rightArm',
    script: `Love that pose? We can save it so ${ROBOT_NAME} can strike it again any time. Let's capture this one!`,
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
function StageNav({ s, go, goConcept, navigate }: { s: State; go: (screen: Screen) => void; goConcept: (i: number) => void; navigate: (path: string) => void }) {
  const stages = [
    { label: 'Welcome', isActive: s.screen === 'welcome', onClick: () => go('welcome') },
    { label: 'Explore', isActive: s.screen === 'blocks', onClick: () => go('blocks') },
    { label: 'Joints', isActive: s.screen === 'concept' && s.conceptIdx === 0, onClick: () => goConcept(0) },
    { label: 'Intent', isActive: s.screen === 'concept' && s.conceptIdx === 1, onClick: () => goConcept(1) },
    { label: 'Safety', isActive: s.screen === 'concept' && s.conceptIdx === 2, onClick: () => goConcept(2) },
    { label: 'Save', isActive: s.screen === 'concept' && s.conceptIdx === 3, onClick: () => goConcept(3) },
    { label: 'Ready', isActive: s.screen === 'ready', onClick: () => go('ready') },
    { label: 'Real robot', isActive: false, onClick: () => navigate('/movemate') },
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
  const safetyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const blockTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const go = (screen: Screen) => dispatch({ type: 'GO', screen })
  const goConcept = (idx: number) => dispatch({ type: 'GO_CONCEPT', idx })
  const nextConcept = () => {
    if (s.conceptIdx < 3) goConcept(s.conceptIdx + 1)
    else go('playground')
  }
  const cameraUrl = getRobotStream() + '/video_feed'

  // safety check timer for concept-2
  useEffect(() => {
    if (s.safetyChecking) {
      safetyTimerRef.current = setTimeout(() => dispatch({ type: 'SAFETY_DONE' }), 3000)
    }
    return () => { if (safetyTimerRef.current) clearTimeout(safetyTimerRef.current) }
  }, [s.safetyChecking])

  // block safety check timer for explore screen
  useEffect(() => {
    if (s.blockChecking) {
      blockTimerRef.current = setTimeout(() => dispatch({ type: 'BLOCK_CONFIRMED' }), 3000)
    }
    return () => { if (blockTimerRef.current) clearTimeout(blockTimerRef.current) }
  }, [s.blockChecking])

  const cc = CONCEPTS[s.conceptIdx] || CONCEPTS[0]
  const safetyColor = s.screen === 'concept' && cc.demo === 'safety' && !s.safetyDone
    ? '#EF6560'
    : s.screen === 'concept' && cc.demo === 'intent' ? '#F0A93A'
    : s.screen === 'playground' && s.playStep === 'blocked' ? '#EF6560'
    : s.screen === 'playground' && s.playStep === 'understanding' ? '#F0A93A'
    : '#3FA76B'
  const safetyLabel = safetyColor === '#EF6560' ? 'Too close!' : safetyColor === '#F0A93A' ? 'Getting near' : 'Safe zone'

  const isConcept = s.screen === 'concept'
  const isBlocks = s.screen === 'blocks'
  const isPlayground = s.screen === 'playground'

  const dots = [0, 1, 2, 3].map(i =>
    i === s.conceptIdx ? 'tut-dot-active' : i < s.conceptIdx ? 'tut-dot-done' : 'tut-dot-upcoming'
  )

  const simHighlight = isBlocks
    ? (s.blockPart ? (s.blockPart === 'Hip' ? 'core' : 'rightArm') : '')
    : isConcept ? cc.highlight
    : ''
  const simCaption = isBlocks && s.blockPart && s.blockDir ? `Simulating: ${s.blockDir} ${s.blockPart}` : ''

  return (
    <div className="tut-root">
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
          <button className="tut-ready-cta" onClick={() => navigate('/movemate')}>
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
              {isPlayground && (
                <>
                  <span className="tut-badge tut-badge-real">REAL ROBOT</span>
                  <div className="tut-colheader-title">You're on your own with {ROBOT_NAME} now</div>
                </>
              )}
            </div>
            {!isPlayground && (
              <button className="tut-skip-btn" onClick={() => go('ready')}>Skip →</button>
            )}
          </div>

          <div className="tut-twocol">
            <SimPanel
              badge={isPlayground ? 'LIVE SIM' : 'SIM'}
              safetyColor={safetyColor}
              safetyLabel={safetyLabel}
              caption={simCaption}
              highlight={simHighlight}
              cameraUrl={cameraUrl}
            />
            <div className="tut-right">
              {isConcept && <ConceptPanel s={s} dispatch={dispatch} cc={cc} nextConcept={nextConcept} />}
              {isBlocks && <BlocksPanel s={s} dispatch={dispatch} goConcept={goConcept} />}
              {isPlayground && <PlaygroundPanel s={s} dispatch={dispatch} goReady={() => go('ready')} />}
            </div>
          </div>
          {s.miniOpen && <MiniGame s={s} dispatch={dispatch} />}
        </>
      )}

      {/* Stage navigator - shown on all screens */}
      <StageNav s={s} go={go} goConcept={goConcept} navigate={navigate} />
    </div>
  )
}

// ---- Concept Panel ----
function ConceptPanel({ s, dispatch, cc, nextConcept }: { s: State; dispatch: React.Dispatch<Action>; cc: typeof CONCEPTS[0]; nextConcept: () => void }) {
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
            <div className="tut-orb-listen-label">
              <span className="tut-orb-listen-dot" />
              Listening… just start talking
            </div>
            <div className="tut-transcript">
              <div className="tut-transcript-label">YOU SAID</div>
              <div className="tut-transcript-text">"{cc.transcript}"</div>
            </div>
          </div>
          <button className="tut-next-btn" onClick={nextConcept}>Got it! Next →</button>
        </>
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
        <>
          <div className="tut-transcript">
            <div className="tut-transcript-label">YOU SAID</div>
            <div className="tut-transcript-text">"{cc.transcript}"</div>
          </div>
          {s.safetyChecking && (
            <div className="tut-checking-card">
              <div className="tut-checking-spinner" />
              <div className="tut-checking-text">Checking safety…</div>
            </div>
          )}
          {!s.safetyChecking && !s.safetyDone && (
            <>
              <div className="tut-safety-card">
                <div className="tut-safety-header">
                  <div className="tut-safety-icon">✕</div>
                  <span className="tut-safety-label">SAFETY CHECK · BLOCKED</span>
                </div>
                <div className="tut-safety-text">Oops! {ROBOT_NAME}'s arm would bump into its own side there. Let's try a smaller angle.</div>
                <button className="tut-btn-bad" onClick={() => dispatch({ type: 'SAFETY_CHECKING' })}>Try a smaller move</button>
              </div>
              <div className="tut-intent-tip">
                <span className="tut-intent-tip-dot" />
                I always check a move is safe before the robot does it — so nobody gets hurt.
              </div>
            </>
          )}
          {!s.safetyChecking && s.safetyDone && (
            <>
              <div className="tut-success-card">
                <div className="tut-check-icon">✓</div>
                <div className="tut-success-text">All clear! That smaller move is safe. Great fix!</div>
              </div>
              <button className="tut-next-btn" onClick={nextConcept}>Got it! Next →</button>
            </>
          )}
          {!s.safetyChecking && !s.safetyDone && (
            <></>
          )}
        </>
      )}

      {/* SAVE */}
      {isSave && (
        <>
          <div className="tut-mic-wrap">
            <div className="tut-orb-container">
              <span className="tut-orb-ring" />
              <div className="tut-orb-core">
                <div className="tut-orb-mic">
                  <div className="tut-orb-mic-body" />
                  <div className="tut-orb-mic-base" />
                  <div className="tut-orb-mic-stem" />
                </div>
              </div>
            </div>
            <div className="tut-transcript">
              <div className="tut-transcript-label">YOU SAID</div>
              <div className="tut-transcript-text">"{cc.transcript}"</div>
            </div>
          </div>
          <button className="tut-next-btn" onClick={() => dispatch({ type: 'OPEN_MINI' })}>Capture this pose →</button>
        </>
      )}
    </div>
  )
}

// ---- Blocks Panel ----
function BlocksPanel({ s, dispatch, goConcept }: { s: State; dispatch: React.Dispatch<Action>; goConcept: (i: number) => void }) {
  const bothSet = !!s.blockPart && !!s.blockDir
  const moveText = bothSet ? `${s.blockDir} ${s.blockPart}` : ''

  const partOptions = ['Shoulder', 'Elbow', 'Wrist', 'Hip']
  const dirOptions = ['Raise', 'Lower', 'Extend', 'Bend']

  return (
    <>
      <div className="tut-blocks-header">
        <div className="tut-blocks-title">Try moving {ROBOT_NAME} yourself</div>
        <div className="tut-blocks-sub">Fill each block — I'll pick sensible defaults for anything you skip.</div>
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
          <div className="tut-tap-hint"><span className="tut-tap-dot" />…or just say it out loud</div>
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
              <div className="tut-block-req">Needs: safety check</div>
            </div>
          </div>
          {bothSet && !s.blockChecking && !s.blockConfirmed && (
            <div className="tut-confirm-btns" style={{ marginTop: 13 }}>
              <button className="tut-btn-primary" style={{ flex: 1 }} onClick={() => dispatch({ type: 'BLOCK_CHECKING' })}>Check safety</button>
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
                <div className="tut-confirm-text">Safety check passed — <strong>{moveText}</strong> is a safe move!</div>
              </div>
              <div className="tut-confirm-btns">
                <button className="tut-btn-primary" style={{ flex: 1 }} onClick={() => goConcept(0)}>Start the lessons →</button>
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

// ---- Playground Panel ----
const STEPPER_CFGS: Record<string, Array<{ state: string; label: string; summary?: string; detail?: string; buttons?: Array<{ label: string; step: string; kind?: string }> }>> = {
  understanding: [
    { state: 'done', label: 'You said', summary: `"Raise ${ROBOT_NAME}'s left arm"` },
    { state: 'active', label: 'Understanding', detail: `I think you want to raise ${ROBOT_NAME}'s LEFT ARM. Does that sound right?`, buttons: [{ label: "Yes, that's it", step: 'safepass' }, { label: 'No, let me try again', step: 'understanding', kind: 'ghost' }] },
    { state: 'upcoming', label: 'Safety check' },
    { state: 'upcoming', label: 'Clarification' },
    { state: 'upcoming', label: 'Execute' },
  ],
  safepass: [
    { state: 'done', label: 'You said', summary: `"Raise ${ROBOT_NAME}'s left arm"` },
    { state: 'done', label: 'Understanding', summary: 'Raise left arm' },
    { state: 'done', label: 'Safety check', summary: 'All clear — no collisions' },
    { state: 'skipped', label: 'Clarification', summary: 'Not needed' },
    { state: 'active', label: 'Execute', detail: 'Ready to raise the left arm 30°. Watch the sim!', buttons: [{ label: 'Go! ▶', step: 'understanding' }] },
  ],
  blocked: [
    { state: 'done', label: 'You said', summary: '"Bend the left elbow all the way back"' },
    { state: 'done', label: 'Understanding', summary: 'Bend left elbow, full range' },
    { state: 'blocked', label: 'Safety check', detail: `${ROBOT_NAME}'s arm would bump into its own side at that angle. Let's try a smaller movement.`, buttons: [{ label: 'Try again', step: 'understanding' }] },
    { state: 'upcoming', label: 'Clarification' },
    { state: 'upcoming', label: 'Execute' },
  ],
}

function PlaygroundPanel({ s, dispatch, goReady }: { s: State; dispatch: React.Dispatch<Action>; goReady: () => void }) {
  const steps = STEPPER_CFGS[s.playStep] || STEPPER_CFGS.understanding
  const demos: Array<[PlayStep, string]> = [['understanding', 'Ask'], ['safepass', 'Pass'], ['blocked', 'Block']]

  return (
    <>
      <div className="tut-play-header">
        <div className="tut-play-header-row">
          <div>
            <div className="tut-play-title">How I'm thinking</div>
            <div className="tut-play-sub">Each step lights up as I work it out.</div>
          </div>
          <div className="tut-play-demos">
            {demos.map(([k, l]) => (
              <button key={k} className={`tut-play-demo-btn ${s.playStep === k ? 'tut-play-demo-active' : 'tut-play-demo-inactive'}`} onClick={() => dispatch({ type: 'SET_PLAY', step: k })}>{l}</button>
            ))}
          </div>
        </div>
      </div>
      <div className="tut-play-body">
        {steps.map((step, i) => {
          const iconCls = `tut-step-icon tut-step-icon-${step.state}`
          const rowCls = `tut-step tut-step-${step.state}`
          const labelCls = step.state === 'upcoming' || step.state === 'skipped' ? 'tut-step-label-off' : 'tut-step-label-on'
          const iconContent = step.state === 'active'
            ? <div className="tut-step-icon-spinner" />
            : step.state === 'done' ? <span className="tut-step-icon-text-done">✓</span>
            : step.state === 'blocked' ? <span className="tut-step-icon-text-done">✕</span>
            : step.state === 'skipped' ? <span className="tut-step-icon-text-skip">—</span>
            : <span className="tut-step-icon-text-num">{i + 1}</span>
          return (
            <div key={i} className={rowCls}>
              <div className="tut-step-header">
                <div className={iconCls}>{iconContent}</div>
                <div style={{ flex: 1 }}>
                  <div className={labelCls}>{step.label}</div>
                  {step.summary && <div className="tut-step-summary">{step.summary}</div>}
                </div>
              </div>
              {step.detail && (
                <div className="tut-step-detail">
                  <div className={step.state === 'blocked' ? 'tut-step-detail-blocked' : 'tut-step-detail-inner'}>{step.detail}</div>
                  {step.buttons && (
                    <div className="tut-step-btns">
                      {step.buttons.map((b, bi) => (
                        <button key={bi} className={b.kind === 'ghost' ? 'tut-step-btn-ghost' : 'tut-step-btn-primary'} onClick={() => dispatch({ type: 'SET_PLAY', step: b.step as PlayStep })}>{b.label}</button>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
      <div className="tut-play-footer">
        <div className="tut-play-mic">
          <div className="tut-play-mic-ring" />
          <div className="tut-play-mic-core">
            <div className="tut-orb-mic" style={{ transform: 'scale(.55)' }}>
              <div className="tut-orb-mic-body" />
              <div className="tut-orb-mic-base" />
            </div>
          </div>
        </div>
        <div>
          <div className="tut-play-mic-label">Ready to try?</div>
          <div className="tut-play-mic-sub">tap or just talk</div>
        </div>
        <button style={{ marginLeft: 'auto' }} className="tut-btn-primary" onClick={goReady}>I'm ready! →</button>
      </div>
    </>
  )
}

// ---- Mini-game overlay ----
const MINI_COLORS = ['#FF6B4A', '#17BEBB', '#7C6CF0']

function MiniGame({ s, dispatch }: { s: State; dispatch: React.Dispatch<Action> }) {
  const capN = 3
  const choosing = s.miniShots >= capN
  const recIdx = 1

  const titleMap = [
    'Take your first shot!',
    'One more time!',
    'Last one!',
    'Pick your favourite take',
  ]
  const subMap = [
    "Strike a pose — we'll capture it 3 times and pick the best!",
    'Hold the same pose again',
    'One final take — make it count!',
    'Tap the one you like best.',
  ]

  return (
    <div className="tut-mini-backdrop">
      <div className="tut-mini-card">
        <div className="tut-mini-badge">POSE ACCURACY GAME</div>
        <div className="tut-mini-title">{titleMap[Math.min(s.miniShots, 3)]}</div>
        <div className="tut-mini-sub">{subMap[Math.min(s.miniShots, 3)]}</div>
        <div className="tut-mini-shots">
          {Array.from({ length: capN }).map((_, i) => {
            const col = MINI_COLORS[i]
            const done = i < s.miniShots
            const picked = s.miniPicked === i
            return (
              <div key={i} className="tut-mini-shot" onClick={choosing ? () => dispatch({ type: 'MINI_PICK', idx: i }) : undefined}>
                <div className={`tut-mini-thumb${picked ? ' tut-mini-thumb-picked' : ''}`} style={{ background: done ? col + '22' : '#F2EDE2' }}>
                  {done ? (
                    <>
                      <div style={{ width: 24, height: 24, borderRadius: '50%', background: col, opacity: .7 }} />
                      <div style={{ width: 42, height: 32, borderRadius: '13px 13px 8px 8px', background: col, opacity: .7, marginTop: -2 }} />
                    </>
                  ) : (
                    <div className="tut-mini-empty-num">{i + 1}</div>
                  )}
                </div>
                {done && i === recIdx && !choosing && <div className="tut-mini-best">★ best</div>}
                {picked && <div className="tut-mini-picked-check">✓</div>}
                <div className="tut-mini-take-label">Take {i + 1}</div>
              </div>
            )
          })}
        </div>
        {!choosing && (
          <button className="tut-mini-capture-btn" onClick={() => dispatch({ type: 'MINI_CAPTURE' })}>
            {s.miniShots === 0 ? 'Capture pose ▶' : `Take ${s.miniShots + 1} of ${capN} ▶`}
          </button>
        )}
        {choosing && s.miniPicked === null && (
          <div className="tut-mini-choose-text">Tap the take you like best.</div>
        )}
        {choosing && s.miniPicked !== null && (
          <button className="tut-mini-save-btn" onClick={() => dispatch({ type: 'MINI_SAVE' })}>Save this pose ✓</button>
        )}
      </div>
    </div>
  )
}
