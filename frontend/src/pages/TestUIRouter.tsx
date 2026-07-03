import { Link } from 'react-router-dom'
import './TestUI.css'

import { useDemoMachine, type DemoState } from '../demo/useDemoMachine'

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

export default function TestUIRouter() {
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
