import { Link } from 'react-router-dom'
import {
  CameraFlash,
  ClassifyCard,
  Countdown,
  DemoCameraFeed,
  RecordIndicator,
  SpeakingBubble,
  prettyClass,
} from '../demo/components'
import { useDemoMachine } from '../demo/useDemoMachine'
import './DemoPage.css'

const POSE_SUGGESTIONS = [
  't-pose', 'dab', 'superhero', 'thinker', 'muscles', 'hand-raised', 'warrior2',
]

export default function DemoPage() {
  const { state, start, retry, exit } = useDemoMachine()
  const running = !['IDLE', 'DONE', 'TIMEOUT', 'ERROR'].includes(state.stage)

  return (
    <div className="demo-root">
      <header className="demo-header">
        <Link to="/" className="demo-back">← Testing Page</Link>
        <h1 className="demo-title">Coral’s Pose Party</h1>
        <div className="demo-stage-chip" data-stage={state.stage}>{stageLabel(state.stage, state)}</div>
      </header>

      <main className="demo-main">
        <section className={`demo-stage demo-stage-${state.stage.toLowerCase()}`}>
          {/* Live camera + overlays */}
          <div className="demo-camera-wrap">
            <DemoCameraFeed />
            <Countdown value={state.countdown} />
            <CameraFlash active={state.flash} />
            {state.classifying && <div className="demo-overlay"><div className="demo-snap">📸</div></div>}
          </div>

          {/* Stage-specific panel */}
          <div className="demo-panel">
            <SpeakingBubble speaking={state.speaking} caption={state.caption} />

            {state.stage === 'IDLE' && (
              <div className="demo-intro-panel demo-pop">
                <p className="demo-lead">Strike your best pose and teach Coral some moves!</p>
                <button className="demo-btn demo-btn-go" onClick={start}>▶ Start the Demo</button>
              </div>
            )}

            {(state.stage === 'INTRO' || state.stage === 'CLASSIFY') && (
              <div className="demo-suggestions">
                <div className="demo-suggestions-title">Try a pose!</div>
                <div className="demo-chips">
                  {POSE_SUGGESTIONS.map((p) => (
                    <span className="demo-chip" key={p}>{prettyClass(p)}</span>
                  ))}
                </div>
              </div>
            )}

            {state.classifyResult && state.stage === 'CLASSIFY' && (
              <ClassifyCard result={state.classifyResult} />
            )}

            {state.stage === 'RECORD' && <RecordIndicator status={state.recordStatus} />}

            {state.stage === 'TIMEOUT' && (
              <div className="demo-prompt demo-pop">
                <p>Proceed movement not detected.</p>
                <div className="demo-prompt-btns">
                  <button className="demo-btn demo-btn-go" onClick={retry}>Try Again</button>
                  <button className="demo-btn demo-btn-exit" onClick={exit}>Exit</button>
                </div>
              </div>
            )}

            {state.stage === 'ERROR' && (
              <div className="demo-prompt demo-pop">
                <p>Oops — {state.error}</p>
                <div className="demo-prompt-btns">
                  <button className="demo-btn demo-btn-go" onClick={retry}>Restart</button>
                  <button className="demo-btn demo-btn-exit" onClick={exit}>Exit</button>
                </div>
              </div>
            )}

            {state.stage === 'DONE' && (
              <div className="demo-prompt demo-pop demo-done">
                <p>🎉 All done! Great teaching!</p>
                <button className="demo-btn demo-btn-go" onClick={retry}>Play Again</button>
              </div>
            )}
          </div>
        </section>
      </main>

      <footer className="demo-footer">
        {running && (
          <>
            <span className="demo-progress">
              Round {Math.min(state.loop + 1, state.totalLoops)} of {state.totalLoops}
            </span>
            <button className="demo-btn demo-btn-exit small" onClick={exit}>Exit Demo</button>
          </>
        )}
      </footer>
    </div>
  )
}

function stageLabel(stage: string, state: { loop: number; totalLoops: number }): string {
  switch (stage) {
    case 'IDLE': return 'Ready'
    case 'INTRO': return 'Welcome'
    case 'CLASSIFY': return `Pose ${state.loop + 1}`
    case 'RECORD': return 'Your Turn'
    case 'OUTRO': return 'Wrap-up'
    case 'DONE': return 'Finished'
    case 'TIMEOUT': return 'Waiting'
    case 'ERROR': return 'Error'
    default: return stage
  }
}
