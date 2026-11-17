import { useEffect, useRef } from 'react'
import { sendAudioForTranscript } from '../../../api/actionSession'
import { move, saveCurrentPose } from '../../../api/robot'
import { captureUtterance } from '../../../audio/capture'
import { SimPanel, AgentBubble, ConceptHeader, countdownAndSnap } from '../parts'
import { type State, type Action } from '../state'

export function ConceptSaveScreen({
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
    try {
      const result = await countdownAndSnap(dispatch)
      if (!result.poseDetected) {
        dispatch({ type: 'SET_ERROR', text: result.detail || "I couldn't see your whole body — step back!" })
        dispatch({ type: 'SET_CAPTURE_PHASE', phase: 'idle' })
        return
      }
      await move(result.commands)
      dispatch({ type: 'SET_CAPTURED', result })
      dispatch({ type: 'SET_CAPTURE_PHASE', phase: 'result' })
    } catch (err) {
      console.error('capture failed', err)
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
