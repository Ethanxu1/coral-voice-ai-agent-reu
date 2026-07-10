import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import './TestUI.css'

import { useDemoMachine, type DemoState } from '../demo/useDemoMachine'
import type { MapFeaturesResult } from '../demo/api'

import Page1_Welcome from './Page1_Welcome'
import Page2_ClassifyInstructions from './Page2_ClassifyInstructions'
import Page3_ClassifyCountdown from './Page3_ClassifyCountdown'
import Page4_ClassifyResults from './Page4_ClassifyResults'
import Page5_RecordInstructions from './Page5_RecordInstructions'
import Page6_RecordMic from './Page6_RecordMic'
import Page7_Name from './Page7_Name'
import Page8_Outro from './Page8_Outro'

/** Props every TestUI page receives from the demo state machine. */
export interface PageProps {
  state: DemoState
  start: () => void
  retry: () => void
  exit: () => void
  /** Submit typed input (text mode) — used by the record/name pages. */
  submitText: (text: string) => void
}

const PAGES: { label: string; component: React.ComponentType<PageProps> }[] = [
  { label: 'Welcome', component: Page1_Welcome },
  { label: 'Get Ready', component: Page2_ClassifyInstructions },
  { label: 'Strike a Pose', component: Page3_ClassifyCountdown },
  { label: 'Results', component: Page4_ClassifyResults },
  { label: 'Your Turn', component: Page5_RecordInstructions },
  { label: 'Listening', component: Page6_RecordMic },
  { label: 'Name It', component: Page7_Name },
  { label: 'All Done', component: Page8_Outro },
]

// Baseline mock state for preview mode. Each page overrides the fields it reads
// (see mockStateForPage) so every screen renders something representative with
// no backend running.
const baseMockState: DemoState = {
  stage: 'INTRO',
  page: 1,
  loop: 0,
  totalLoops: 3,
  speaking: false,
  countdown: null,
  flash: false,
  classifying: false,
  classifyResult: null,
  recording: false,
  recordStatus: 'idle',
  caption: '',
  error: null,
  poseName: null,
  moves: [],
  inputMode: 'voice',
  awaitingText: false,
}

// A pose result with no real frame — pages fall back to <DummyFrame/>.
const mockClassifyResult: MapFeaturesResult = {
  poseDetected: true,
  detail: null,
  commands: [],
  imageB64: null,
  legMode: 'retarget',
  poseClass: null,
}

/** Build representative display state for a given 1-based page in preview mode. */
function mockStateForPage(page: number): DemoState {
  const per: Record<number, Partial<DemoState>> = {
    1: { page: 1, caption: 'Say hello to Coral!' },
    2: { page: 2, caption: 'Cross your hands in front of you when you are ready!' },
    3: { page: 3, stage: 'CLASSIFY', countdown: 3 },
    4: { page: 4, stage: 'CLASSIFY', classifyResult: mockClassifyResult, caption: "Now I'll copy your pose!" },
    5: { page: 5, stage: 'RECORD', caption: 'Your turn — tell me how to fix my pose!' },
    6: { page: 6, stage: 'RECORD', recordStatus: 'recording', caption: "I'm listening… 🎤" },
    7: {
      page: 7,
      stage: 'NAME',
      classifyResult: mockClassifyResult,
      poseName: 'Superhero',
      caption: '',
    },
    8: {
      page: 8,
      stage: 'OUTRO',
      moves: [
        { name: 'Superhero', frame: null },
        { name: 'T-Rex', frame: null },
        { name: 'Robot', frame: null },
      ],
    },
  }
  return { ...baseMockState, ...per[page] }
}

export default function TestUIRouter() {
  const [searchParams] = useSearchParams()
  const [preview, setPreview] = useState(searchParams.has('preview'))

  if (preview) {
    return <PreviewMode onExit={() => setPreview(false)} />
  }
  return <LiveDemo onPreview={() => setPreview(true)} />
}

/** The real, backend-driven demo (speaker/robot/vision servers must be running). */
function LiveDemo({ onPreview }: { onPreview: () => void }) {
  const { state, start, retry, exit, toggleInputMode, submitText } = useDemoMachine()
  const pageIndex = Math.min(Math.max(state.page, 1), PAGES.length) - 1
  const Page = PAGES[pageIndex].component
  const props: PageProps = { state, start, retry, exit, submitText }
  const running = !['IDLE', 'DONE', 'TIMEOUT', 'ERROR'].includes(state.stage)

  return (
    <div className="tui-root">
      <nav className="tui-nav">
        <div className="tui-nav-left">
          <Link to="/">
            <button className="tui-btn tui-btn-home">← Back</button>
          </Link>
          <span style={{ fontWeight: 700, fontSize: 13, opacity: 0.6 }}>{PAGES[pageIndex].label}</span>
        </div>
        <div className="tui-nav-center">
          {running && (
            <div className="tui-nav-title">
              Round {Math.min(state.loop + 1, state.totalLoops)} / {state.totalLoops}
            </div>
          )}
        </div>
        <div className="tui-nav-right">
          <button
            className="tui-btn"
            onClick={onPreview}
            title="Browse every page without any backend servers running"
          >
            👁 Preview
          </button>
          <button
            className="tui-btn"
            onClick={toggleInputMode}
            title="Switch between speaking and typing your answers"
          >
            {state.inputMode === 'voice' ? '🎤 Voice' : '⌨️ Text'}
          </button>
          {running && <button className="tui-btn" onClick={exit}>Exit</button>}
        </div>
      </nav>

      {/* Active page, remounted per page+loop so entry animations replay. */}
      <Page key={`${state.page}-${state.loop}`} {...props} />

      {/* Stage overlays on top of the active page. */}
      {state.stage === 'IDLE' && <StartOverlay onStart={start} />}
      {state.stage === 'TIMEOUT' && (
        <PromptOverlay
          title="I didn't see the go-ahead 🙈"
          message="Cross your hands to start, or exit."
          primaryLabel="Try Again"
          onPrimary={retry}
          onExit={exit}
        />
      )}
      {state.stage === 'ERROR' && (
        <PromptOverlay
          title="Oops — something went wrong"
          message={state.error || 'Unexpected error.'}
          primaryLabel="Restart"
          onPrimary={retry}
          onExit={exit}
        />
      )}
      {state.stage === 'DONE' && (
        <PromptOverlay
          title="🎉 All done!"
          message="Great job teaching Coral your poses!"
          primaryLabel="Play Again"
          onPrimary={retry}
          onExit={exit}
        />
      )}
    </div>
  )
}

/** Backend-free page browser: steps through all pages with mock state so the UI
 *  can be viewed/designed without the speaker/robot/vision servers running. */
function PreviewMode({ onExit }: { onExit: () => void }) {
  const [page, setPage] = useState(1)
  const pageIndex = page - 1
  const Page = PAGES[pageIndex].component
  const state = mockStateForPage(page)
  // Runner controls are inert in preview — nothing should hit the network.
  const noop = () => {}
  const props: PageProps = { state, start: noop, retry: noop, exit: onExit, submitText: noop }

  const go = (delta: number) =>
    setPage((p) => Math.min(Math.max(p + delta, 1), PAGES.length))

  return (
    <div className="tui-root">
      <nav className="tui-nav">
        <div className="tui-nav-left">
          <button className="tui-btn tui-btn-home" onClick={onExit}>← Live demo</button>
          <span style={{ fontWeight: 700, fontSize: 13, opacity: 0.6 }}>
            Preview · {PAGES[pageIndex].label}
          </span>
        </div>
        <div className="tui-nav-center">
          <div className="tui-nav-title">Page {page} / {PAGES.length}</div>
        </div>
        <div className="tui-nav-right">
          <button className="tui-btn" onClick={() => go(-1)} disabled={page === 1}>← Prev</button>
          <button className="tui-btn" onClick={() => go(1)} disabled={page === PAGES.length}>Next →</button>
        </div>
      </nav>

      {/* Remount per page so entry animations replay as you step through. */}
      <Page key={page} {...props} />
    </div>
  )
}

function StartOverlay({ onStart }: { onStart: () => void }) {
  return (
    <div className="tui-overlay">
      <div className="tui-overlay-card tui-pop">
        <div className="tui-overlay-title">Let's Teach Coral Some Poses! 🤖</div>
        <div className="tui-overlay-msg">Strike your best pose and Coral will learn it.</div>
        <button className="tui-btn tui-btn-go" onClick={onStart}>▶ Start</button>
      </div>
    </div>
  )
}

function PromptOverlay({
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
  onExit: () => void
}) {
  return (
    <div className="tui-overlay">
      <div className="tui-overlay-card tui-pop">
        <div className="tui-overlay-title">{title}</div>
        <div className="tui-overlay-msg">{message}</div>
        <div className="tui-overlay-btns">
          <button className="tui-btn tui-btn-go" onClick={onPrimary}>{primaryLabel}</button>
          <button className="tui-btn" onClick={onExit}>Exit</button>
        </div>
      </div>
    </div>
  )
}
