import { useEffect, useRef, useState } from 'react'
import { type ActionResult, sendAudioForTranscript } from '../../../api/actionSession'
import { classifyIntent, type IntentResult } from '../../../api/robot'
import { captureUtterance } from '../../../audio/capture'
import AIReasoningStepper from '../../../components/AIReasoningStepper'
import { SimPanel, AgentBubble, MicOrb, SuggestedChips, TranscriptBox, buildStepperItems, ConceptHeader } from '../parts'
import { type State, type Action } from '../state'

export function ConceptIntentScreen({
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
  const [intent, setIntent] = useState<IntentResult | null>(null)

  useEffect(() => {
    return () => { abortRef.current?.abort() }
  }, [])

  const listen = async () => {
    dispatch({ type: 'SET_ERROR', text: '' })
    dispatch({ type: 'SET_TRANSCRIPT', text: '' })
    dispatch({ type: 'CLEAR_STEPPER' })
    dispatch({ type: 'SET_VOICE_PHASE', phase: 'listening' })
    setIntent(null)
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
      const result = await classifyIntent(text, false, undefined, 'tutorial-intent')
      dispatch({ type: 'LOG', text: `intent: ${result.type} — ${JSON.stringify(result)}` })
      setIntent(result)
      const understanding = intentDescription(result)
      dispatch({ type: 'SET_STEPPER', stepper: { understanding } })
      dispatch({ type: 'SET_VOICE_PHASE', phase: 'idle' })
    } catch (err) {
      console.error('intent demo failed', err)
      dispatch({ type: 'SET_ERROR', text: 'Something went wrong — try again!' })
      dispatch({ type: 'SET_VOICE_PHASE', phase: 'idle' })
    }
  }

  const execute = async (text: string) => {
    dispatch({ type: 'SET_VOICE_PHASE', phase: 'thinking' })
    try {
      await sendCommand(text)
      dispatch({ type: 'SET_STEPPER', stepper: { safety: { ok: true }, execute: 'Moved in the simulator' } })
      dispatch({ type: 'SET_VOICE_PHASE', phase: 'done' })
    } catch (err) {
      dispatch({ type: 'SET_ERROR', text: 'Could not run that move — try again.' })
      dispatch({ type: 'SET_VOICE_PHASE', phase: 'idle' })
    }
  }

  const correct = (side: string) => {
    const corrected = `${s.transcript} — ${side}`
    dispatch({ type: 'SET_TRANSCRIPT', text: corrected })
    dispatch({ type: 'CLEAR_STEPPER' })
    dispatch({ type: 'SET_STEPPER', stepper: { command: corrected, understanding: `I think you want to ${side}` } })
    execute(corrected)
  }

  const prompts = ['move the arm up', 'raise your arm']

  return (
    <>
      <ConceptHeader index={1} title="Instructions & Intent" onSkip={onNext} />
      <div className="tut-twocol">
        <SimPanel cameraUrl={cameraUrl} />
        <div className="tut-right">
          <div className="tut-right-scroll">
            <AgentBubble>
              Sometimes I'm not sure what you mean. I'll show you my best guess, and you can fix it if I'm wrong.
            </AgentBubble>

            {!intent && s.voicePhase !== 'done' && (
              <>
                <SuggestedChips prompts={prompts} onPrompt={() => listen()} />
                <MicOrb phase={s.voicePhase} onClick={listen} label='Tap and say "move the arm up"' />
              </>
            )}

            <TranscriptBox text={s.transcript} />
            {s.error && <div className="tut-waiting-text">{s.error}</div>}

            {intent && s.voicePhase !== 'done' && (
              <div className="tut-intent-card">
                <div className="tut-intent-header">
                  <div className="tut-intent-icon">?</div>
                  <span className="tut-intent-label">MY BEST GUESS</span>
                </div>
                <div className="tut-intent-text">{intentDescription(intent)}</div>
                <div className="tut-intent-btns">
                  <button className="tut-btn-primary" onClick={() => execute(s.transcript)}>
                    Yes, do it
                  </button>
                  <button className="tut-btn-ghost" onClick={() => correct('use the left arm')}>
                    No, left arm
                  </button>
                  <button className="tut-btn-ghost" onClick={() => correct('use the right arm')}>
                    Right arm
                  </button>
                </div>
              </div>
            )}

            <AIReasoningStepper steps={buildStepperItems(s.stepper)} />

            {s.voicePhase === 'done' && (
              <>
                <div className="tut-intent-tip">
                  <span className="tut-intent-tip-dot" />
                  I'm making a guess — I can't read your mind! You can always correct me.
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

export function intentDescription(result: IntentResult): string {
  if (result.type === 'motion') return `I think you want to: ${result.description}`
  if (result.type === 'clarification') return `I'm not sure — ${result.question}`
  if (result.type === 'immediate') return `I understood: ${result.intent}`
  return `I heard: "${result.text}"`
}
