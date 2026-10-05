import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChatArea, ConnectionHealthDot } from './RefinedDemo'
import { LiveStream } from './DummyStream'
import RobotViewer from '../components/RobotViewer'
import { useConnectionStatus } from '../components/ConnectionStatus'
import { usePoseWebSocket } from '../hooks/usePoseWebSocket'
import {
  killSpeech,
  openActionSession,
  resetPose,
  setHiplessFollow,
  speak,
  stopSubjectSelection,
} from '../demo/api'
import type { ActionSession } from '../demo/api'
import type { RefinedChatMsg } from '../demo/useRefinedDemoMachine'
import GestureFigure from '../rps/GestureFigure'
import StandardPicture from '../rps/StandardPicture'
import SkeletonView, { followReadiness } from '../rps/SkeletonView'
import { classifyGesture } from '../rps/classify'
import { poseRobot, resetRobot } from '../rps/robotPose'
import { BEATS, GESTURES, GESTURE_BY_ID, type GestureId } from '../rps/gestures'
import './RefinedDemo.css'
import './RockPaperScissors.css'

export type RpsMode = 'learn' | 'play'
type Outcome = 'win' | 'lose' | 'draw'

const COUNTDOWN_STEPS = ['3', '2', '1']
const COUNTDOWN_STEP_MS = 850
const SAMPLE_WINDOW_MS = 1300
const SAMPLE_EVERY_MS = 50
const MATCH_HOLD_MS = 700

const CHIP_LEARN = 'Learn gestures'
const CHIP_PLAY = "Let's play"
const CHIP_START = "I'm ready!"
const CHIP_AGAIN = 'Play again'

export const RPS_PATH = '/rock-paper-scissors'

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))


function judge(child: GestureId, robot: GestureId): Outcome {
  if (child === robot) return 'draw'
  return BEATS[child] === robot ? 'win' : 'lose'
}

const OUTCOME_TEXT: Record<Outcome, string> = {
  win: 'You win!',
  lose: 'I win this one!',
  draw: "It's a draw!",
}

export default function RockPaperScissors({ mode }: { mode: RpsMode }) {
  const navigate = useNavigate()
  const services = useConnectionStatus()
  const { bodyLandmarks, trackingLost } = usePoseWebSocket()

  const [lesson, setLesson] = useState<GestureId | null>(null)
  const [messages, setMessages] = useState<RefinedChatMsg[]>([])
  const [countdown, setCountdown] = useState<string | null>(null)
  const [shooting, setShooting] = useState(false)
  const [busy, setBusy] = useState(false)
  const [score, setScore] = useState({ win: 0, lose: 0, draw: 0 })
  const sessionRef = useRef<ActionSession | null>(null)

  // The vision server may still be in multi-person mode from the main demo,
  // where no body landmarks are published until someone is selected, so the
  // mount effect below switches it back to plain single-person tracking.
  const detected = useMemo(
    () => (trackingLost ? null : classifyGesture(bodyLandmarks)),
    [bodyLandmarks, trackingLost],
  )
  // The game samples the camera outside React's render cycle.
  const detectedRef = useRef<GestureId | null>(null)
  detectedRef.current = detected

  const runIdRef = useRef(0)

  const say = useCallback((text: string, chips?: string[], voice: string | null = text) => {
    setMessages((m) => [...m, { role: 'agent', text, chips }])
    if (voice) {
      killSpeech()
        .then(() => speak({ text: voice }))
        .catch(() => {})
    }
  }, [])

  const showLesson = useCallback(
    (id: GestureId) => {
      const g = GESTURE_BY_ID[id]
      setLesson(id)
      say(`${g.label}! ${g.tagline}`, [
        ...GESTURES.filter((x) => x.id !== id).map((x) => x.label),
        CHIP_PLAY,
      ])
    },
    [say],
  )

  const playRound = useCallback(async () => {
    const run = ++runIdRef.current
    const cancelled = () => run !== runIdRef.current
    setBusy(true)
    try {
      await resetRobot()
    } catch (e) {
      console.warn('robot reset failed', e)
    }

    for (const step of COUNTDOWN_STEPS) {
      if (cancelled()) return
      setCountdown(step)
      await sleep(COUNTDOWN_STEP_MS)
    }
    if (cancelled()) return
    setCountdown(null)

    // Shoot: the robot strikes its move while the camera watches the child.
    setShooting(true)
    const robot = GESTURES[Math.floor(Math.random() * GESTURES.length)].id
    poseRobot(GESTURE_BY_ID[robot].robotPulses, 400).catch((e) => console.warn('robot move failed', e))

    const votes: Record<GestureId, number> = { rock: 0, paper: 0, scissors: 0 }
    const end = Date.now() + SAMPLE_WINDOW_MS
    while (Date.now() < end) {
      if (cancelled()) return
      const seen = detectedRef.current
      if (seen) votes[seen]++
      await sleep(SAMPLE_EVERY_MS)
    }
    if (cancelled()) return

    const best = (Object.keys(votes) as GestureId[]).reduce((a, b) => (votes[b] > votes[a] ? b : a))
    const child = votes[best] > 0 ? best : null

    setShooting(false)
    setBusy(false)
    if (!child) {
      say(
        "Hmm, I couldn't see your move! Step back so your arms are in view, then try again.",
        [CHIP_AGAIN, CHIP_LEARN],
      )
      return
    }
    const outcome = judge(child, robot)
    setScore((s) => ({ ...s, [outcome]: s[outcome] + 1 }))
    const you = GESTURE_BY_ID[child]
    const me = GESTURE_BY_ID[robot]
    say(
      `You made ${you.label} ${you.emoji} and I made ${me.label} ${me.emoji}. ${OUTCOME_TEXT[outcome]}`,
      [CHIP_AGAIN, CHIP_LEARN],
    )
  }, [say])

  const onChip = useCallback(
    (text: string) => {
      if (busy) return
      setMessages((m) => [...m, { role: 'child', text }])
      const gesture = GESTURES.find((g) => g.label === text)
      if (gesture) return showLesson(gesture.id)
      if (text === CHIP_LEARN) return navigate(`${RPS_PATH}/learn`)
      if (text === CHIP_PLAY) return navigate(`${RPS_PATH}/play`)
      if (text === CHIP_START || text === CHIP_AGAIN) return playRound()
    },
    [busy, navigate, showLesson, playRound],
  )

  // Greet once on entry; hand the robot back to a neutral stand on exit.
  useEffect(() => {
    stopSubjectSelection()
    resetRobot().catch(() => {})
    if (mode === 'learn') {
      say('Pick a move and I will show you how to do it. Then try it in front of the camera!', [
        ...GESTURES.map((g) => g.label),
        CHIP_PLAY,
      ])
    } else {
      say("Let's play! Count 1, 2, 3 with me, and when I say shoot, strike your move!", [CHIP_START, CHIP_LEARN])
    }
    return () => {
      runIdRef.current++
      killSpeech()
      // In Learn the follower session below stops following first, then resets.
      if (mode === 'play') resetPose().catch(() => {})
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Learn: let the simulator robot follow the child (the same follow pipeline the
  // main demo uses), arms and head only.
  useEffect(() => {
    if (mode !== 'learn') return
    let cancelled = false
    const run = async () => {
      await resetRobot().catch(() => {})
      await sleep(600)
      if (cancelled) return
      await setHiplessFollow(true)
      if (cancelled) return
      const session = openActionSession()
      sessionRef.current = session
      try {
        await session.sendText('follow my movement', 'immediate')
      } catch (e) {
        console.warn('start follow failed', e)
      }
    }
    run()
    return () => {
      cancelled = true
      const session = sessionRef.current
      sessionRef.current = null
      if (session) {
        session
          .sendText('stop following', 'immediate')
          .catch(() => {})
          .finally(() => {
            session.close()
            resetPose().catch(() => {})
            setHiplessFollow(false)
          })
      } else {
        setHiplessFollow(false)
      }
    }
  }, [mode])

  // In a lesson, cheer when the camera sees the child make the move they picked.
  const cheeredRef = useRef<GestureId | null>(null)
  useEffect(() => {
    cheeredRef.current = null
  }, [lesson])
  useEffect(() => {
    if (mode !== 'learn' || !lesson || detected !== lesson || cheeredRef.current === lesson) return
    const t = setTimeout(() => {
      cheeredRef.current = lesson
      say(`That's it, that's ${GESTURE_BY_ID[lesson].label}! Great job!`, undefined, `Great job! That's ${GESTURE_BY_ID[lesson].label}!`)
    }, MATCH_HOLD_MS)
    return () => clearTimeout(t)
  }, [mode, lesson, detected, say])

  const leave = () => navigate('/')
  const toMenu = () => !busy && navigate(RPS_PATH)
  const lessonDef = lesson ? GESTURE_BY_ID[lesson] : null
  const lessonMatched = lesson !== null && detected === lesson
  const readiness = followReadiness(trackingLost ? [] : bodyLandmarks)

  return (
    <div className="rd-root">
      <header className="rd-topbar">
        <div className="rd-topbar-left">
          <div className="rd-logo">
            coral<span>.</span>
          </div>
        </div>
        <div className="rd-topbar-right">
          <button className="rd-topbar-btn ghost" onClick={toMenu}>
            Menu
          </button>
          <button className="rd-topbar-btn ghost" onClick={() => { resetRobot().catch(() => {}) }}>
            Return to stand
          </button>
          <ConnectionHealthDot services={services} />
          <button className="rd-topbar-btn danger" onClick={leave}>
            End
          </button>
        </div>
      </header>

      <main className="rd-main">
        {mode === 'learn' ? (
          <div className="rd-camera-panel rps-quad">
            {/* 1. The standard move: a still picture, not the simulator. */}
            <div className="rps-cell rps-cell-standard">
              <div className="rps-cell-title">
                1 · Standard{lessonDef ? ` ${lessonDef.label} ${lessonDef.emoji}` : ''}
              </div>
              {lessonDef ? (
                <StandardPicture key={lessonDef.id} gesture={lessonDef} />
              ) : (
                <div className="rps-cell-empty">Pick Rock, Paper or Scissors →</div>
              )}
            </div>

            {/* 2. The simulator robot trying to follow the child. */}
            <div className="rps-cell">
              <div className="rd-sim-grid" />
              <div className="rd-sim-vignette" />
              <div className="rps-cell-title">2 · Robot following you</div>
              <RobotViewer embedded />
            </div>

            {/* 3. The camera, with the tracker's overlay. */}
            <div className="rps-cell rps-cell-dark">
              <div className="rps-cell-title">3 · What the camera sees</div>
              <LiveStream badge={false} />
            </div>

            {/* 4. The stick figure the tracker believes is you. */}
            <div className="rps-cell rps-cell-dark">
              <div className="rps-cell-title">4 · What I think your pose is</div>
              <SkeletonView landmarks={trackingLost ? [] : bodyLandmarks} />
              <div className={`rps-note ${readiness.ok ? 'ok' : 'warn'}`}>{readiness.message}</div>
              {lessonDef && (
                <div className={`rps-match ${lessonMatched ? 'ok' : ''}`}>
                  {lessonMatched
                    ? `✓ That's ${lessonDef.label}!`
                    : detected
                    ? `I see ${GESTURE_BY_ID[detected].label} — try ${lessonDef.label}`
                    : `I don't see ${lessonDef.label} yet`}
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="rd-camera-panel">
            <div className="rd-sim-grid" />
            <div className="rd-sim-vignette" />
            <div className="rd-sim-badge"><span className="rd-sim-badge-dot" />SIM</div>
            <div className="rd-sim-safety"><span className="rd-sim-safety-dot" />Safe zone</div>
            <RobotViewer embedded />
            <div className="rd-pip">
              <LiveStream badge={false} />
              <div className="rd-pip-live">
                <span className="rd-pip-live-dot" />
                <span className="rd-pip-live-text">LIVE</span>
              </div>
            </div>

            <div className="rd-follow-badge rps-score-badge">
              You {score.win} · Draw {score.draw} · CORAL {score.lose}
            </div>
            <div className="rd-follow-badge rps-seen-badge">
              {detected ? `I see: ${GESTURE_BY_ID[detected].label} ${GESTURE_BY_ID[detected].emoji}` : 'I see: nothing yet'}
            </div>
            {shooting && <div className="rd-captured-badge rps-shoot-badge">Shoot!</div>}
          </div>
        )}

        <div className="rd-right-panel">
          {lessonDef && mode === 'learn' && (
            <div className="rps-lesson-card">
              <GestureFigure gesture={lessonDef} />
              <div className="rps-lesson-text">
                <div className="rps-lesson-title">
                  {lessonDef.emoji} {lessonDef.label}
                </div>
                <ol>
                  {lessonDef.steps.map((s) => (
                    <li key={s}>{s}</li>
                  ))}
                </ol>
              </div>
            </div>
          )}
          <ChatArea messages={messages} onChip={onChip} agentTyping={false} />
        </div>
      </main>

      {countdown != null && (
        <div className="rd-countdown-modal">
          <div className="rd-countdown-card">
            <div className="rd-countdown-label">Get ready!</div>
            <span key={countdown} className="rd-countdown-num">
              {countdown}
            </span>
          </div>
        </div>
      )}
    </div>
  )
}
