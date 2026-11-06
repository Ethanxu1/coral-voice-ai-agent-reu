import { useEffect, useRef } from 'react'
import { type ActionResult, sendAudioForTranscript } from '../../../api/actionSession'
import { captureUtterance } from '../../../audio/capture'
import AIReasoningStepper from '../../../components/AIReasoningStepper'
import { SimPanel, AgentBubble, MicOrb, SuggestedChips, TranscriptBox, buildStepperItems, ConceptHeader } from '../parts'
import { type State, type Action } from '../state'

export function ConceptJointsScreen({
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

  useEffect(() => {
    return () => { abortRef.current?.abort() }
  }, [])

  const listen = async (_prompt: string) => {
    dispatch({ type: 'SET_ERROR', text: '' })
    dispatch({ type: 'SET_TRANSCRIPT', text: '' })
    dispatch({ type: 'CLEAR_STEPPER' })
    dispatch({ type: 'SET_VOICE_PHASE', phase: 'listening' })
    const ctrl = new AbortController()
    abortRef.current = ctrl
    try {
      const blob = await captureUtterance({ signal: ctrl.signal })
      dispatch({ type: 'SET_VOICE_PHASE', phase: 'thinking' })
      const text = await sendAudioForTranscript(blob)
      if (!text.trim()) {
        dispatch({ type: 'SET_ERROR', text: "I didn't catch that — try again!" })
        dispatch({ type: 'SET_VOICE_PHASE', phase: 'idle' })
        return
      }
      dispatch({ type: 'SET_TRANSCRIPT', text })
      dispatch({ type: 'SET_STEPPER', stepper: { command: text } })
      await sendCommand(text)
      dispatch({ type: 'SET_STEPPER', stepper: { understanding: `I think you want to: ${text}`, safety: { ok: true }, execute: 'Moved in the simulator' } })
      dispatch({ type: 'SET_VOICE_PHASE', phase: 'done' })
    } catch (err) {
      console.error('joints voice demo failed', err)
      dispatch({ type: 'SET_ERROR', text: 'Something went wrong — try again!' })
      dispatch({ type: 'SET_VOICE_PHASE', phase: 'idle' })
    }
  }

  const prompts = ['raise your right arm', 'look up', 'bend your left elbow']

  return (
    <>
      <ConceptHeader index={0} title="Joints & Movement" onSkip={onNext} />
      <div className="tut-twocol">
        <SimPanel cameraUrl={cameraUrl} />
        <div className="tut-right">
          <div className="tut-right-scroll">
            <AgentBubble>
              You just moved my joints by hand. Now try with your voice! Tap the mic and tell me what to do.
            </AgentBubble>

            <SuggestedChips prompts={prompts} onPrompt={listen} />

            <MicOrb phase={s.voicePhase} onClick={() => listen(prompts[0])} label='Tap and say "raise your right arm"' />

            <TranscriptBox text={s.transcript} />
            {s.error && <div className="tut-waiting-text">{s.error}</div>}

            <AIReasoningStepper steps={buildStepperItems(s.stepper)} />

            {s.voicePhase === 'done' && (
              <button className="tut-next-btn" onClick={onNext}>
                Got it! Next →
              </button>
            )}
          </div>
        </div>
      </div>
    </>
  )
}
