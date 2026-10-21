import { useEffect, useRef } from 'react'
import { type ActionResult } from '../../../api/actionSession'
import { resetPose } from '../../../api/robot'
import AIReasoningStepper from '../../../components/AIReasoningStepper'
import { SimPanel, AgentBubble, TranscriptBox, buildStepperItems, ConceptHeader } from '../parts'
import { ROBOT_NAME, type State, type Action } from '../state'

export function ConceptSafetyScreen({
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
  sendCommand: (
    text: string,
    intentType?: 'motion' | 'conversation' | 'immediate' | 'clarification',
    description?: string,
  ) => Promise<ActionResult>
}) {
  const abortRef = useRef<AbortController | null>(null)
  const didReset = useRef(false)

  useEffect(() => {
    if (didReset.current) return
    didReset.current = true
    resetPose().catch(() => {})
    return () => { abortRef.current?.abort() }
  }, [])

  const demoCommand = 'rotate your right arm all the way into your stomach'

  const runDemo = async () => {
    dispatch({ type: 'SET_ERROR', text: '' })
    dispatch({ type: 'SET_TRANSCRIPT', text: demoCommand })
    dispatch({ type: 'CLEAR_STEPPER' })
    dispatch({ type: 'SET_VOICE_PHASE', phase: 'thinking' })
    try {
      dispatch({ type: 'SET_STEPPER', stepper: { command: demoCommand, understanding: 'Rotate right arm inward' } })
      await sendCommand(demoCommand, 'motion', 'Rotate right arm inward')
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
              I always check a move is safe before I try it. First I'll stand back up — then press the button and watch what happens when I try to rotate my right arm all the way into my stomach.
            </AgentBubble>

            {s.voicePhase !== 'done' && (
              <button
                className="tut-next-btn"
                onClick={runDemo}
                disabled={s.voicePhase === 'thinking'}
              >
                {s.voicePhase === 'thinking' ? 'Running safety check…' : 'Show me the safety check'}
              </button>
            )}

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
