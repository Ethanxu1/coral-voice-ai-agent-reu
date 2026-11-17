import { useEffect, useRef, useState } from 'react'
import { type ActionSession, sendAudioForTranscript } from '../../../api/actionSession'
import { classifyIntent, type IntentResult, move } from '../../../api/robot'
import { captureUtterance } from '../../../audio/capture'
import AIReasoningStepper from '../../../components/AIReasoningStepper'
import { SimPanel, AgentBubble, MicOrb, SuggestedChips, TranscriptBox, buildStepperItems, countdownAndSnap } from '../parts'
import { intentDescription } from './ConceptIntentScreen'
import { ROBOT_NAME, type State, type Action } from '../state'

export function FreePracticeScreen({
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
  const abortRef = useRef<AbortController | null>(null)
  const [pendingIntent, setPendingIntent] = useState<IntentResult | null>(null)

  const clear = () => {
    dispatch({ type: 'SET_ERROR', text: '' })
    dispatch({ type: 'SET_TRANSCRIPT', text: '' })
    dispatch({ type: 'CLEAR_STEPPER' })
    setPendingIntent(null)
  }

  const listen = async () => {
    clear()
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
      const result = await classifyIntent(text, s.following, undefined, 'tutorial-practice')
      dispatch({ type: 'LOG', text: `practice intent: ${result.type}` })
      dispatch({ type: 'SET_STEPPER', stepper: { understanding: intentDescription(result) } })
      await handleIntent(text, result)
    } catch (err) {
      console.error('free practice failed', err)
      dispatch({ type: 'SET_ERROR', text: 'Something went wrong — try again!' })
      dispatch({ type: 'SET_VOICE_PHASE', phase: 'idle' })
    }
  }

  const handleIntent = async (text: string, result: IntentResult) => {
    if (result.type === 'clarification') {
      dispatch({ type: 'SET_STEPPER', stepper: { clarification: result.question } })
      dispatch({ type: 'SET_VOICE_PHASE', phase: 'idle' })
      return
    }
    if (result.type === 'conversation') {
      dispatch({ type: 'SET_STEPPER', stepper: { safety: { ok: true }, execute: 'Talking with you' } })
      await session.current?.sendText(text, 'conversation')
      dispatch({ type: 'SET_VOICE_PHASE', phase: 'done' })
      dispatch({ type: 'MARK_PRACTICE_READY' })
      return
    }
    if (result.type === 'motion') {
      setPendingIntent(result)
      dispatch({ type: 'SET_STEPPER', stepper: { safety: { ok: true }, execute: 'Waiting for your approval' } })
      dispatch({ type: 'SET_VOICE_PHASE', phase: 'idle' })
      return
    }
    if (result.type === 'immediate') {
      const intent = result.intent
      if (intent === 'follow_start') {
        dispatch({ type: 'SET_FOLLOWING', active: true })
        await session.current?.sendText(text, 'immediate')
        dispatch({ type: 'SET_STEPPER', stepper: { safety: { ok: true }, execute: 'Now following you' } })
      } else if (intent === 'follow_stop') {
        dispatch({ type: 'SET_FOLLOWING', active: false })
        await session.current?.sendText(text, 'immediate')
        dispatch({ type: 'SET_STEPPER', stepper: { safety: { ok: true }, execute: 'Stopped following' } })
      } else if (intent === 'capture') {
        dispatch({ type: 'SET_STEPPER', stepper: { safety: { ok: true }, execute: 'Capture started' } })
        // Simplify: just tell them to use the save concept; or run mini-capture inline.
        await runMiniCapture()
      } else if (intent === 'save_robot_pose' || intent === 'naming') {
        dispatch({ type: 'SET_STEPPER', stepper: { safety: { ok: true }, execute: 'Ready to save current pose' } })
      } else {
        await session.current?.sendText(text, 'immediate')
        dispatch({ type: 'SET_STEPPER', stepper: { safety: { ok: true }, execute: 'Done' } })
      }
      dispatch({ type: 'SET_VOICE_PHASE', phase: 'done' })
      dispatch({ type: 'MARK_PRACTICE_READY' })
    }
  }

  const approveMotion = async () => {
    if (!pendingIntent || pendingIntent.type !== 'motion') return
    dispatch({ type: 'SET_VOICE_PHASE', phase: 'thinking' })
    try {
      await session.current?.sendText(s.transcript, 'motion', pendingIntent.description)
      dispatch({ type: 'SET_STEPPER', stepper: { execute: 'Moved in the simulator' } })
      dispatch({ type: 'SET_VOICE_PHASE', phase: 'done' })
      dispatch({ type: 'MARK_PRACTICE_READY' })
    } catch (err) {
      dispatch({ type: 'SET_ERROR', text: 'Could not run that move.' })
      dispatch({ type: 'SET_VOICE_PHASE', phase: 'idle' })
    }
    setPendingIntent(null)
  }

  const rejectMotion = () => {
    setPendingIntent(null)
    dispatch({ type: 'SET_STEPPER', stepper: { execute: 'Cancelled — try saying it differently' } })
    dispatch({ type: 'SET_VOICE_PHASE', phase: 'idle' })
  }

  const runMiniCapture = async () => {
    try {
      const result = await countdownAndSnap(dispatch, false)
      if (result.poseDetected) {
        await move(result.commands)
      }
      dispatch({ type: 'SET_CAPTURE_PHASE', phase: 'idle' })
    } catch (err) {
      dispatch({ type: 'SET_ERROR', text: 'Capture did not work that time.' })
      dispatch({ type: 'SET_CAPTURE_PHASE', phase: 'idle' })
    }
  }

  useEffect(() => {
    return () => { abortRef.current?.abort() }
  }, [])

  const prompts = [
    'raise your right arm',
    'follow my movement',
    'capture my pose',
    'what can you do?',
  ]

  return (
    <>
      <div className="tut-colheader">
        <div className="tut-colheader-left">
          <div className="tut-logo-box">
            <div className="tut-logo-diamond" />
          </div>
          <span className="tut-badge tut-badge-real">FREE PRACTICE</span>
          <div className="tut-colheader-title">Try anything you learned</div>
        </div>
        <button
          className="tut-skip-btn"
          onClick={onNext}
          style={{ color: s.practiceReady ? 'var(--accent)' : undefined }}
        >
          {s.practiceReady ? "I'm ready →" : 'Skip →'}
        </button>
      </div>

      <div className="tut-twocol">
        <SimPanel
          cameraUrl={cameraUrl}
          overlay={
            s.capturePhase === 'countdown' && s.countdown != null ? (
              <div className="tut-capture-countdown">
                <span key={s.countdown}>{s.countdown}</span>
              </div>
            ) : null
          }
        />
        <div className="tut-right">
          <div className="tut-right-scroll">
            <AgentBubble>
              Now it's your turn! Try a voice command and watch the stepper. When you feel ready, tap "I'm ready."
            </AgentBubble>

            <SuggestedChips prompts={prompts} onPrompt={() => listen()} />
            <MicOrb phase={s.voicePhase} onClick={listen} label="Tap and tell me what to do" />

            <TranscriptBox text={s.transcript} />
            {s.error && <div className="tut-waiting-text">{s.error}</div>}

            {pendingIntent && (
              <div className="tut-intent-card">
                <div className="tut-intent-header">
                  <div className="tut-intent-icon">?</div>
                  <span className="tut-intent-label">APPROVE THIS MOVE?</span>
                </div>
                <div className="tut-intent-text">{intentDescription(pendingIntent)}</div>
                <div className="tut-intent-btns">
                  <button className="tut-btn-primary" onClick={approveMotion}>
                    Yes, do it
                  </button>
                  <button className="tut-btn-ghost" onClick={rejectMotion}>
                    No, cancel
                  </button>
                </div>
              </div>
            )}

            <AIReasoningStepper steps={buildStepperItems(s.stepper)} />

            <button
              className="tut-next-btn"
              onClick={onNext}
              disabled={!s.practiceReady}
              style={{ opacity: !s.practiceReady ? 0.5 : 1 }}
            >
              I'm ready! Meet the real {ROBOT_NAME} →
            </button>
          </div>
        </div>
      </div>
    </>
  )
}
