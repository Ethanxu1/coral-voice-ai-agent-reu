import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { LiveStream } from '../components/LiveStream'
import RobotViewer from '../components/RobotViewer'
import type { ActionSession } from '../api/actionSession'
import { resetPose } from '../api/robot'
import { stopSubjectSelection } from '../api/vision'
import { killSpeech, playShutter, speak } from '../audio/speech'
import CornerMenu from '../rps/CornerMenu'
import { startFollowing, stopFollowing } from '../rps/useRobotFollow'
import { copyPoseFromCamera, poseFromRobot, waitForSaveCommand } from '../poseDesigner/capture'
import { MAX_NAME_LENGTH, saveCustomPose } from '../poseDesigner/customPoses'
import { useDesignConversation, type MicState } from '../poseDesigner/useDesignConversation'
import { sleep } from '../utils/sleep'
import './DanceGame.css'
import './PoseDesigner.css'

type Step = 'choose' | 'capture' | 'refine' | 'name'
/** How the child's pose gets onto the robot: a camera snapshot, or following them live. */
type Mode = 'snap' | 'follow'

/** Seconds from pressing the button to the snapshot / freeze: time to step back and pose. (Saying "save this pose" freezes at once.) */
const COUNTDOWN_S = 5
const SAVED_MS = 1500

const MIC_TEXT: Record<MicState, string> = {
  listening: "I'm listening…",
  thinking: 'Thinking…',
  speaking: 'Talking…',
  off: "I can't hear you. Check the microphone, or type below.",
}

const INTRO =
  "Here's your pose! Tell me what to change, like lift your right arm higher. Say I'm done when you like it."

function HowToPlay({ onClose }: { onClose: () => void }) {
  return (
    <div className="help" onClick={onClose}>
      <div className="help-card" onClick={(e) => e.stopPropagation()}>
        <h2>How to play</h2>
        <ol className="help-steps">
          <li><span>📸</span><p><b>Copy my pose</b> takes a picture of you; <b>Follow me</b> lets CORAL copy you live until you say <b>save this pose</b>.</p></li>
          <li><span>🗣️</span><p>Tell CORAL what to change: "lift your right arm higher", "bring your arms closer". The see-through CORAL shows the change.</p></li>
          <li><span>👍</span><p>Say <b>yes</b> to make the change, or tell CORAL to do it differently. Say <b>I'm done</b> to name your pose.</p></li>
        </ol>
        <p className="help-note">Left and right are CORAL's own. Only the arms can change. Saved poses show up in the Dance Game.</p>
        <button className="big-btn small" onClick={onClose}>OK</button>
      </div>
    </div>
  )
}

/**
 * Design your own pose: get your pose onto CORAL (camera snapshot, or CORAL
 * follows you and freezes), refine it by talking ("lift your right arm
 * higher"; each change is previewed as a ghost and made only once you say
 * yes), then type a name. Saved poses become Dance Game moves. When done it
 * goes back where it came from (`location.state.from`, else home).
 */
export default function PoseDesigner() {
  const navigate = useNavigate()
  const back: string = (useLocation().state as { from?: string } | null)?.from ?? '/'
  const [step, setStep] = useState<Step>('choose')
  const [mode, setMode] = useState<Mode>('snap')
  const [countdown, setCountdown] = useState<number | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [help, setHelp] = useState(false)
  const [name, setName] = useState('')
  const [typed, setTyped] = useState('')
  const [saved, setSaved] = useState(false)

  const poseRef = useRef<Record<string, number>>({})
  const followRef = useRef<ActionSession | null>(null)
  const saveListenRef = useRef<AbortController | null>(null)
  const tokenRef = useRef(0)

  const talk = useDesignConversation(step === 'refine', INTRO, poseRef, () => setStep('name'))

  const stopListeningForSave = () => {
    saveListenRef.current?.abort()
    saveListenRef.current = null
  }

  const stopFollow = async () => {
    stopListeningForSave()
    const s = followRef.current
    followRef.current = null
    if (s) await stopFollowing(s)
  }

  useEffect(() => {
    stopSubjectSelection()
    resetPose().catch(() => {})
    return () => {
      tokenRef.current++
      killSpeech()
      stopFollow().finally(() => resetPose().catch(() => {}))
    }
  }, [])

  const sayAndWait = (text: string) => {
    setNote(text)
    return speak({ text }).catch(() => {})
  }
  const say = (text: string) => void sayAndWait(text)

  const choose = async (m: Mode) => {
    const token = ++tokenRef.current
    setMode(m)
    setStep('capture')
    if (m === 'snap') {
      say("Strike a pose! Press the button and I'll take a picture.")
      return
    }
    setNote('Getting ready to copy you…')
    try {
      const session = await startFollowing()
      if (tokenRef.current !== token) return void stopFollowing(session)
      followRef.current = session
      await sayAndWait("I'm copying you! Make your pose, then say save this pose.")
      if (tokenRef.current === token) listenForSave()
    } catch (e) {
      console.warn('follow failed', e)
      setNote("I can't copy you right now. Is the server running?")
    }
  }

  /** While following: "save this pose" freezes right away, on the pose held when it was said. */
  const listenForSave = async () => {
    const abort = new AbortController()
    saveListenRef.current = abort
    let pulses: Record<string, number>
    try {
      pulses = await waitForSaveCommand(abort.signal)
    } catch (e) {
      if (!abort.signal.aborted) console.warn('listening for "save this pose" failed', e)
      return
    } finally {
      abort.abort()
    }
    const token = ++tokenRef.current
    setCountdown(null)
    playShutter()
    await finishCapture('follow', () => tokenRef.current === token, pulses)
  }

  /** Count down, then snap or freeze, and move on to refining the pose. */
  const capture = async () => {
    const token = ++tokenRef.current
    const alive = () => tokenRef.current === token
    setNote(null)
    for (let n = COUNTDOWN_S; n > 0; n--) {
      setCountdown(n)
      await sleep(1000)
      if (!alive()) return
    }
    setCountdown(null)
    if (mode === 'snap') playShutter()
    await finishCapture(mode, alive)
  }

  /**
   * Snap the camera (or stop following), put the robot in the pose (`pulses`,
   * else wherever it is), and move on to refining it.
   */
  const finishCapture = async (m: Mode, alive: () => boolean, pulses?: Record<string, number>) => {
    try {
      if (m === 'follow') {
        await stopFollow()
      } else {
        const problem = await copyPoseFromCamera()
        if (problem) return void (alive() && say(problem))
      }
      if (!alive()) return
      poseRef.current = await poseFromRobot(pulses)
      if (alive()) setStep('refine')
    } catch (e) {
      console.warn('capture failed', e)
      if (alive()) setNote("Something went wrong. Is the camera on? Try again.")
    }
  }

  const startOver = async () => {
    tokenRef.current++
    killSpeech()
    setCountdown(null)
    setNote(null)
    setStep('choose')
    await stopFollow()
    resetPose().catch(() => {})
  }

  const save = async () => {
    saveCustomPose(name, poseRef.current)
    setSaved(true)
    speak({ text: `Saved ${name.trim()}!` }).catch(() => {})
    await sleep(SAVED_MS)
    navigate(back)
  }

  const sendTyped = (e: React.FormEvent) => {
    e.preventDefault()
    if (!typed.trim()) return
    talk.sendTyped(typed.trim())
    setTyped('')
  }

  const robot = (
    <div className="robot">
      <div className="floor" />
      <RobotViewer embedded look="stage" ghost={step === 'refine' ? talk.ghost : null} />
    </div>
  )

  return (
    <div className="dance pd">
      <header className="top">
        <h1>Design your own pose</h1>
        <CornerMenu onHelp={() => setHelp(true)} menuPath={null} />
      </header>

      {step === 'choose' && (
        <main className="pd-choose">
          <p className="pd-lead">How should CORAL learn your pose?</p>
          <div className="pd-options">
            <button className="pd-option" onClick={() => choose('snap')}>
              <span className="em">📸</span>
              <b>Copy my pose</b>
              <small>Strike a pose and CORAL takes a picture</small>
            </button>
            <button className="pd-option follow" onClick={() => choose('follow')}>
              <span className="em">🪞</span>
              <b>Follow me</b>
              <small>CORAL moves with you, then freezes</small>
            </button>
          </div>
          <button className="pd-link" onClick={() => navigate(back)}>← Back</button>
        </main>
      )}

      {step === 'capture' && (
        <main className="pd-main">
          <section className="pd-cam">
            <LiveStream badge={false} />
            {countdown !== null && <div key={countdown} className="pd-count">{countdown}</div>}
          </section>
          <section className="stage">
            <div className="bubble">{note ?? (mode === 'snap' ? 'Get ready…' : 'Freeze in…')}</div>
            {robot}
            <div className="pd-actions">
              <button className="pd-link" onClick={startOver}>← Start over</button>
              <button className="big-btn" onClick={capture} disabled={countdown !== null}>
                {mode === 'snap' ? '📸 Take picture' : '🧊 Freeze!'}
              </button>
            </div>
          </section>
        </main>
      )}

      {step === 'refine' && (
        <main className="pd-main refine">
          <section className="stage">{robot}</section>
          <section className="pd-talk">
            <div key={talk.coral} className="bubble">{talk.coral || '…'}</div>
            {talk.proposal && (
              <div className="pd-proposal">
                <div className="pd-ghost-key"><i /> See-through CORAL shows the change</div>
                <ul>
                  {talk.proposal.changes.map((c) => (
                    <li key={c.control}>
                      {c.label} <b>{c.degrees > 0 ? '+' : ''}{c.degrees}°</b>
                    </li>
                  ))}
                </ul>
                <div className="pd-yesno">
                  <button className="yes" onClick={() => talk.sendTyped('yes')}>👍 Yes</button>
                  <button className="no" onClick={() => talk.sendTyped('no')}>👎 No</button>
                </div>
              </div>
            )}
            <div className={`pd-mic ${talk.mic}`}>
              <span className="dot" style={{ '--level': Math.min(1, talk.level / 40) } as React.CSSProperties} />
              {MIC_TEXT[talk.mic]}
              {talk.heard && <span className="heard">You said: “{talk.heard}”</span>}
            </div>
            <form className="pd-type" onSubmit={sendTyped}>
              <input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="…or type to CORAL" maxLength={200} />
              <button type="submit" disabled={!typed.trim()}>Send</button>
            </form>
            <div className="pd-actions">
              <button className="pd-link" onClick={startOver}>← Start over</button>
              <button className="big-btn small" onClick={() => setStep('name')}>I'm done ✓</button>
            </div>
          </section>
        </main>
      )}

      {step === 'name' && (
        <main className="pd-main refine">
          <section className="stage">{robot}</section>
          <section className="pd-talk">
            {saved ? (
              <div className="bubble">⭐ Saved “{name.trim()}”!</div>
            ) : (
              <form className="pd-name" onSubmit={(e) => { e.preventDefault(); if (name.trim()) save() }}>
                <label htmlFor="pd-name">What's your pose called?</label>
                <input id="pd-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={MAX_NAME_LENGTH} placeholder="My super pose" autoFocus />
                <div className="pd-actions">
                  <button type="button" className="pd-link" onClick={() => setStep('refine')}>← Keep changing it</button>
                  <button type="submit" className="big-btn small" disabled={!name.trim()}>Save ⭐</button>
                </div>
              </form>
            )}
          </section>
        </main>
      )}

      {help && <HowToPlay onClose={() => setHelp(false)} />}
    </div>
  )
}
