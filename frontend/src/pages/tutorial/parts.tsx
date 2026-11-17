import { useEffect, useState } from 'react'
import { resetPose } from '../../api/robot'
import { mapFeatures, type MapFeaturesResult } from '../../api/vision'
import { playShutter } from '../../audio/speech'
import { sleep } from '../../utils/sleep'
import { type StepItem } from '../../components/AIReasoningStepper'
import RobotViewer from '../../components/RobotViewer'
import { ROBOT_NAME, type Screen, type VoicePhase, type StepperState, type State, type Action, SCREENS } from './state'

export function RobotIllustration({ wave = false, happy = false }: { wave?: boolean; happy?: boolean }) {
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

export function Confetti() {
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

export function SimPanel({
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
              objectFit: 'contain',
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

export function AgentBubble({ children }: { children: React.ReactNode }) {
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

export function MicOrb({
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

export function SuggestedChips({ prompts, onPrompt }: { prompts: string[]; onPrompt: (p: string) => void }) {
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

export function TranscriptBox({ text }: { text: string }) {
  if (!text) return null
  return (
    <div className="tut-transcript">
      <div className="tut-transcript-label">YOU SAID</div>
      <div className="tut-transcript-text">"{text}"</div>
    </div>
  )
}

export function buildStepperItems(stepper: StepperState): StepItem[] {
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

export function ConceptHeader({
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

export function StageNav({ screen, onJump }: { screen: Screen; onJump: (screen: Screen) => void }) {
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

export function FacilitatorOverlay({
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

/**
 * On-screen 3-2-1 countdown, then snap the camera and retarget the child's
 * pose. `showAnalyzing` switches the capture panel to its "analyzing" state
 * while the vision server works.
 */
export async function countdownAndSnap(
  dispatch: React.Dispatch<Action>,
  showAnalyzing = true,
): Promise<MapFeaturesResult> {
  dispatch({ type: 'SET_CAPTURE_PHASE', phase: 'countdown' })
  for (const n of [3, 2, 1]) {
    dispatch({ type: 'SET_COUNTDOWN', n })
    await sleep(1000)
  }
  dispatch({ type: 'SET_COUNTDOWN', n: null })
  if (showAnalyzing) dispatch({ type: 'SET_CAPTURE_PHASE', phase: 'analyzing' })
  playShutter()
  return mapFeatures()
}
