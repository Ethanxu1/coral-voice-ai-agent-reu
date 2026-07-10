import { useReducer, useEffect, useRef, useCallback } from 'react'
import { getRobotStream } from '../demo/robotConfig'
import { captureUtterance, sendAudioForTranscript, listPoses } from '../demo/api'
import './MoveMate.css'

const ASSISTANT_NAME = 'CORAL'

type Screen = 'idle' | 'following' | 'thinking' | 'countdown' | 'captured' | 'finetune' | 'naming' | 'library' | 'exit'

interface Msg {
  role: 'agent' | 'child' | 'system'
  text?: string
  chips?: Array<{ label: string; screen: Screen }>
}

interface State {
  screen: Screen
  count: number
  transcript: string
  messages: Msg[]
  poses: string[]
  posesLoaded: boolean
}

type Action =
  | { type: 'GO'; screen: Screen }
  | { type: 'SET_COUNT'; n: number }
  | { type: 'SET_TRANSCRIPT'; text: string }
  | { type: 'SET_MESSAGES'; msgs: Msg[] }
  | { type: 'SET_POSES'; poses: string[] }

function buildMessages(screen: Screen, transcript: string, name: string): Msg[] {
  const chip = (label: string, s: Screen): { label: string; screen: Screen } => ({ label, screen: s })
  const A = (text: string, chips?: Array<{ label: string; screen: Screen }>): Msg => ({ role: 'agent', text, chips })
  const U = (text: string): Msg => ({ role: 'child', text })
  const SY = (text: string): Msg => ({ role: 'system', text })

  const flows: Record<Screen, Msg[]> = {
    idle: [
      A(`Hi, I'm ${name}! Move around and I'll follow you — or just tell me what to do.`),
      A('Try saying one of these:', [chip('Follow my movement', 'following'), chip('Capture my pose', 'thinking')]),
    ],
    following: [
      U('Follow my movement!'),
      A("You got it — I'm mirroring your every move on the robot. Strike a pose, then say \"capture\"!"),
      A('', [chip('Capture my pose', 'countdown')]),
    ],
    thinking: [
      U(transcript || 'Capture my pose!'),
      A('Okay! Getting the robot ready — strike your best pose!'),
    ],
    countdown: [
      U(transcript || 'Capture my pose!'),
      A('Great! Hold still — capturing your pose now…'),
    ],
    captured: [
      SY('Pose captured'),
      A('Awesome pose! Want to fine-tune it, or should we save it?', [chip('Fine-tune it', 'finetune'), chip('Save it', 'naming')]),
    ],
    finetune: [
      U('Raise the right arm a little higher.'),
      A('Got it — lifting the right arm up a bit. How does that look?'),
      U('Perfect!'),
      A('Looking great! Ready to give it a name?', [chip('Name & save', 'naming'), chip('One more tweak', 'finetune')]),
    ],
    naming: [
      U(transcript || 'Capture my pose!'),
      A("Let's give it a name so you can use it again. What should we call it?"),
    ],
    library: [],
    exit: [],
  }
  return flows[screen] || []
}

function reducer(s: State, a: Action): State {
  switch (a.type) {
    case 'GO': {
      const msgs = buildMessages(a.screen, s.transcript, ASSISTANT_NAME)
      return { ...s, screen: a.screen, messages: msgs, count: 3 }
    }
    case 'SET_COUNT': return { ...s, count: a.n }
    case 'SET_TRANSCRIPT': return { ...s, transcript: a.text }
    case 'SET_MESSAGES': return { ...s, messages: a.msgs }
    case 'SET_POSES': return { ...s, poses: a.poses, posesLoaded: true }
    default: return s
  }
}

const initMessages = buildMessages('idle', '', ASSISTANT_NAME)
const initState: State = {
  screen: 'idle',
  count: 3,
  transcript: '',
  messages: initMessages,
  poses: [],
  posesLoaded: false,
}

const POSE_COLORS = ['#FF6B4A', '#17BEBB', '#E8A33B', '#7C6CF0', '#EF6F9C']

const STATUS_MAP: Record<Screen, string> = {
  idle: "I'm listening…",
  following: 'Following your moves',
  thinking: 'Hmm, let me think…',
  countdown: 'Get ready…',
  captured: 'Got your pose!',
  finetune: 'Listening for tweaks…',
  naming: 'Say a name…',
  library: 'Pick a pose to strike',
  exit: 'See you next time!',
}

function RobotIllustration() {
  return (
    <div className="mm-robot">
      <div className="mm-robot-neck-wrap">
        <div className="mm-robot-antenna" />
        <div className="mm-robot-neck" />
      </div>
      <div className="mm-robot-head">
        <div className="mm-robot-eye" />
        <div className="mm-robot-eye" />
      </div>
      <div className="mm-robot-torso-wrap">
        <div className="mm-robot-torso">
          <div className="mm-robot-chest">
            <div className="mm-robot-bar" style={{ width: 6, height: 14 }} />
            <div className="mm-robot-bar" style={{ width: 6, height: 26 }} />
            <div className="mm-robot-bar" style={{ width: 6, height: 18 }} />
            <div className="mm-robot-bar" style={{ width: 6, height: 10 }} />
          </div>
        </div>
        <div className="mm-robot-arm mm-robot-arm-left">
          <div className="mm-robot-joint" />
          <div className="mm-robot-limb" />
        </div>
        <div className="mm-robot-arm mm-robot-arm-right">
          <div className="mm-robot-joint" />
          <div className="mm-robot-limb" />
        </div>
      </div>
      <div className="mm-robot-legs">
        <div className="mm-robot-leg" />
        <div className="mm-robot-leg" />
      </div>
    </div>
  )
}

export default function MoveMate() {
  const [s, dispatch] = useReducer(reducer, initState)
  const countRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const countTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const cancelRef = useRef(false)
  const countValRef = useRef(3)
  const streamUrl = `${getRobotStream()}/video_feed`

  const go = useCallback((screen: Screen) => dispatch({ type: 'GO', screen }), [])

  // countdown auto-advance
  useEffect(() => {
    if (s.screen === 'countdown') {
      countValRef.current = 3
      dispatch({ type: 'SET_COUNT', n: 3 })
      countRef.current = setInterval(() => {
        countValRef.current -= 1
        if (countValRef.current <= 0) {
          clearInterval(countRef.current!)
          countRef.current = null
          dispatch({ type: 'SET_COUNT', n: 1 })
          countTimeoutRef.current = setTimeout(() => go('captured'), 750)
        } else {
          dispatch({ type: 'SET_COUNT', n: countValRef.current })
        }
      }, 850)
    }
    return () => {
      if (countRef.current) clearInterval(countRef.current)
      if (countTimeoutRef.current) clearTimeout(countTimeoutRef.current)
    }
  }, [s.screen, go])

  // load poses when library opens
  useEffect(() => {
    if (s.screen === 'library' && !s.posesLoaded) {
      listPoses().then(poses => dispatch({ type: 'SET_POSES', poses })).catch(() => {
        dispatch({ type: 'SET_POSES', poses: ['Superhero', 'T-Rex', 'Star Jump'] })
      })
    }
  }, [s.screen, s.posesLoaded])

  // voice capture for idle → thinking
  const handleVoiceCapture = useCallback(async () => {
    if (s.screen !== 'idle' && s.screen !== 'captured') return
    go('thinking')
    try {
      cancelRef.current = false
      const blob = await captureUtterance({ silenceMs: 900, maxMs: 8000, threshold: 0.012 })
      if (cancelRef.current) return
      const text = await sendAudioForTranscript(blob)
      if (cancelRef.current) return
      dispatch({ type: 'SET_TRANSCRIPT', text })
      go('countdown')
    } catch {
      go('idle')
    }
  }, [s.screen, go])

  const showOrb = s.screen !== 'naming'
  const isLibrary = s.screen === 'library'
  const isExit = s.screen === 'exit'

  const poses = s.posesLoaded && s.poses.length > 0
    ? s.poses
    : ['Superhero', 'T-Rex', 'Star Jump', 'Ninja', 'Big Wave']

  return (
    <div className="mm-root">
      {/* Top bar */}
      <div className="mm-topbar">
        <div className="mm-logo">
          <div className="mm-logo-box"><div className="mm-logo-diamond" /></div>
          <div>
            <div className="mm-logo-name">{ASSISTANT_NAME}</div>
            <div className="mm-logo-sub">ROBOTICS STUDIO</div>
          </div>
        </div>
        <div className="mm-topbar-right">
          <button className="mm-poses-btn" onClick={() => go('library')}>
            <span className="mm-poses-dot" />
            My Poses · {poses.length}
          </button>
          <button className="mm-exit-btn" onClick={() => go('exit')}>
            <span className="mm-exit-sq" />
            Exit
          </button>
        </div>
      </div>

      {/* Main row */}
      <div className="mm-main-row">
        {/* Camera panel */}
        <div className="mm-camera">
          <div className="mm-camera-grid" />
          <div className="mm-camera-vignette" />

          {/* SIM badge top-left */}
          <div className="mm-sim-badge">
            <span className="mm-sim-badge-dot" />
            SIM
          </div>

          {/* Safety indicator top-right */}
          <div className="mm-sim-safety">
            <span className="mm-sim-safety-dot" />
            Safe zone
          </div>

          {/* Robot illustration centered */}
          <RobotIllustration />

          {/* MuJoCo label */}
          <div className="mm-sim-label">[ MuJoCo joint simulation ]</div>

          {/* Camera PiP top-right */}
          <div className="mm-pip">
            <img
              src={streamUrl}
              style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover', borderRadius: 14 }}
              onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
              alt="camera"
            />
            <div className="mm-pip-live">
              <span className="mm-pip-live-dot" />
              <span className="mm-pip-live-text">LIVE</span>
            </div>
            <div className="mm-pip-icon" />
            <div className="mm-pip-label">[ live camera feed ]</div>
          </div>

          {/* following badge */}
          {s.screen === 'following' && (
            <div className="mm-following-badge">
              <span className="mm-following-dot" />
              <span className="mm-following-text">Mirroring your moves</span>
            </div>
          )}

          {/* finetune marker */}
          {s.screen === 'finetune' && (
            <div className="mm-finetune-marker">
              <div className="mm-finetune-ring" />
              <div className="mm-finetune-pill">Right arm ↑ higher</div>
            </div>
          )}

          {/* countdown overlay */}
          {s.screen === 'countdown' && (
            <div className="mm-countdown-overlay">
              <div className="mm-countdown-title">Strike your pose!</div>
              <div className="mm-countdown-ring-wrap">
                <div className="mm-countdown-ring-bg" />
                <div className="mm-countdown-ring-spin" />
                <div className="mm-countdown-num">{s.count}</div>
              </div>
            </div>
          )}

          {/* captured overlay */}
          {s.screen === 'captured' && (
            <div className="mm-captured-overlay">
              <div className="mm-captured-flash" />
              <div className="mm-captured-border" />
              <div className="mm-captured-pill">
                <div className="mm-captured-check">
                  <span style={{ width: 8, height: 4, borderLeft: '2.5px solid var(--accent)', borderBottom: '2.5px solid var(--accent)', transform: 'rotate(-45deg)', marginTop: -2, display: 'block' }} />
                </div>
                Pose captured!
              </div>
            </div>
          )}

          {/* naming card overlay */}
          {s.screen === 'naming' && (
            <div className="mm-naming-overlay">
              <div className="mm-naming-card">
                <div className="mm-naming-badge">NAMING YOUR POSE</div>
                <div className="mm-naming-title">What should we call it?</div>
                <div className="mm-naming-text">
                  Superhero<span className="mm-naming-caret" />
                </div>
                <div className="mm-naming-listen">
                  <span className="mm-naming-listen-dot" />
                  Listening… just say a name
                </div>
                <button className="mm-naming-save-btn" onClick={() => go('library')}>Save this pose</button>
              </div>
            </div>
          )}

          {/* Voice orb */}
          {showOrb && (
            <div className="mm-orb-wrap" style={{ pointerEvents: s.screen === 'idle' || s.screen === 'captured' ? 'auto' : 'none' }}>
              <div className="mm-orb-status">{STATUS_MAP[s.screen]}</div>
              <div className="mm-orb-container" onClick={handleVoiceCapture} style={{ cursor: s.screen === 'idle' ? 'pointer' : 'default' }}>
                <div className="mm-orb-pulse" />
                <div className="mm-orb-pulse mm-orb-pulse2" />
                <div className="mm-orb-pulse mm-orb-pulse3" />
                <div className="mm-orb-core">
                  {/* listening */}
                  {s.screen !== 'thinking' && s.screen !== 'countdown' && (
                    <div className="mm-orb-waves">
                      {[0, .15, .3, .45, .6].map((d, i) => (
                        <div key={i} className="mm-orb-bar" style={{ animationDelay: `${d}s` }} />
                      ))}
                    </div>
                  )}
                  {/* thinking */}
                  {s.screen === 'thinking' && (
                    <div className="mm-orb-dots">
                      {[0, .2, .4].map((d, i) => (
                        <div key={i} className="mm-orb-dot" style={{ animationDelay: `${d}s` }} />
                      ))}
                    </div>
                  )}
                  {/* countdown */}
                  {s.screen === 'countdown' && (
                    <div className="mm-orb-count">{s.count}</div>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Right panel */}
        <div className="mm-right">
          <div className="mm-right-header">
            <div className="mm-right-header-icon">
              <div className="mm-right-header-bars">
                <div className="mm-right-header-bar" style={{ width: 3, height: 8 }} />
                <div className="mm-right-header-bar" style={{ width: 3, height: 15 }} />
                <div className="mm-right-header-bar" style={{ width: 3, height: 11 }} />
              </div>
            </div>
            <div>
              <div className="mm-right-header-name">{ASSISTANT_NAME}</div>
              <div className="mm-right-header-status">
                <span className="mm-right-header-dot" />
                <span className="mm-right-header-status-text">{STATUS_MAP[s.screen]}</span>
              </div>
            </div>
          </div>

          {/* Chat body */}
          {!isLibrary && (
            <>
              <div className="mm-chat-body">
                {s.messages.map((m, i) => (
                  <div key={i}>
                    {m.text !== undefined && m.text !== '' && (
                      <div className={`mm-msg-${m.role}`}>{m.text}</div>
                    )}
                    {m.chips && m.chips.length > 0 && (
                      <div className="mm-chips">
                        {m.chips.map((c, ci) => (
                          <button key={ci} className="mm-chip" onClick={() => go(c.screen)}>{c.label}</button>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
              <div className="mm-chat-footer">
                <span className="mm-chat-footer-dot" />
                <span className="mm-chat-footer-label">Listening…</span>
                <span className="mm-chat-footer-hint">just start talking</span>
              </div>
            </>
          )}

          {/* Library */}
          {isLibrary && (
            <>
              <div className="mm-library-body">
                <div>
                  <div className="mm-library-title">My Poses · {poses.length}</div>
                  <div className="mm-library-sub">Say a pose's name and the robot will strike it.</div>
                </div>
                <div className="mm-library-grid">
                  {poses.map((name, i) => {
                    const col = POSE_COLORS[i % POSE_COLORS.length]
                    return (
                      <div key={i} className="mm-pose-card">
                        <div className="mm-pose-thumb" style={{ background: col + '1f' }}>
                          <div className="mm-pose-thumb-head" style={{ background: col }} />
                          <div className="mm-pose-thumb-body" style={{ background: col }} />
                        </div>
                        <div className="mm-pose-footer">
                          <span className="mm-pose-name">{name}</span>
                          <span style={{ color: col, fontSize: 12 }}>▶</span>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
              <div className="mm-library-footer">
                <button className="mm-library-again-btn" onClick={() => go('idle')}>Make another pose</button>
                <button className="mm-library-done-btn" onClick={() => go('exit')}>I'm done</button>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Exit overlay */}
      {isExit && (
        <div className="mm-exit-overlay">
          <div className="mm-exit-card">
            <div className="mm-exit-title">Great job today!</div>
            <div className="mm-exit-sub">
              You created <span style={{ color: 'var(--accent)', fontWeight: 800 }}>{poses.length} new poses</span> with the robot.
            </div>
            <div className="mm-exit-poses">
              {poses.slice(0, 5).map((name, i) => {
                const col = POSE_COLORS[i % POSE_COLORS.length]
                return (
                  <div key={i} className="mm-exit-pose">
                    <div className="mm-exit-pose-thumb" style={{ background: col + '22' }}>
                      <div style={{ width: 18, height: 18, borderRadius: '50%', background: col, opacity: .65 }} />
                      <div style={{ width: 30, height: 24, borderRadius: '13px 13px 7px 7px', background: col, opacity: .65, marginTop: -2 }} />
                    </div>
                    <div className="mm-exit-pose-name">{name}</div>
                  </div>
                )
              })}
            </div>
            <div className="mm-exit-btns">
              <button className="mm-exit-start-btn" onClick={() => go('idle')}>Start again</button>
              <button className="mm-exit-done-btn" onClick={() => go('idle')}>All done</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
