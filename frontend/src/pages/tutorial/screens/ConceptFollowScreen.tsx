import { useEffect } from 'react'
import { type ActionSession } from '../../../api/actionSession'
import { move } from '../../../api/robot'
import { sleep } from '../../../utils/sleep'
import { SimPanel, AgentBubble, ConceptHeader, countdownAndSnap } from '../parts'
import { type State, type Action } from '../state'

export function ConceptFollowScreen({
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
      dispatch({ type: 'SET_FOLLOWING', active: false })
      // Move on to save concept automatically after a brief pause.
      await sleep(1200)
      onNext()
    } catch (err) {
      console.error('follow capture failed', err)
      dispatch({ type: 'SET_ERROR', text: 'Something went wrong — try again!' })
      dispatch({ type: 'SET_CAPTURE_PHASE', phase: 'idle' })
    }
  }

  useEffect(() => {
    return () => {
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
