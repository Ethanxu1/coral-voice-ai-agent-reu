import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChatArea } from './RefinedDemo'
import { LiveStream } from './DummyStream'
import RobotViewer from '../components/RobotViewer'
import { usePoseWebSocket } from '../hooks/usePoseWebSocket'
import { killSpeech, speak, stopSubjectSelection } from '../demo/api'
import type { RefinedChatMsg } from '../demo/useRefinedDemoMachine'
import GestureFigure from '../rps/GestureFigure'
import StandardPicture from '../rps/StandardPicture'
import SkeletonView, { followReadiness } from '../rps/SkeletonView'
import RpsTopbar, { RPS_PATH } from '../rps/RpsTopbar'
import { classifyGesture, gestureScores } from '../rps/classify'
import { useRobotFollow } from '../rps/useRobotFollow'
import { GESTURES, GESTURE_BY_ID, type GestureId } from '../rps/gestures'
import './RefinedDemo.css'
import './RockPaperScissors.css'

const MATCH_HOLD_MS = 700

const CHIP_PLAY = "Let's play"

/** Learn screen: pick a move, see how to do it, and see what the system thinks you are doing. */
export default function RockPaperScissorsLearn() {
  const navigate = useNavigate()
  const { bodyLandmarks, trackingLost } = usePoseWebSocket()

  const [lesson, setLesson] = useState<GestureId | null>(null)
  const [messages, setMessages] = useState<RefinedChatMsg[]>([])

  useRobotFollow()

  // The vision server may still be in multi-person mode from the main demo,
  // where no body landmarks are published until someone is selected, so the
  // mount effect below switches it back to plain single-person tracking.
  const detected = useMemo(
    () => (trackingLost ? null : classifyGesture(bodyLandmarks)),
    [bodyLandmarks, trackingLost],
  )
  const scores = useMemo(
    () => (trackingLost ? null : gestureScores(bodyLandmarks)),
    [bodyLandmarks, trackingLost],
  )

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

  const onChip = useCallback(
    (text: string) => {
      setMessages((m) => [...m, { role: 'child', text }])
      const gesture = GESTURES.find((g) => g.label === text)
      if (gesture) return showLesson(gesture.id)
      if (text === CHIP_PLAY) return navigate(`${RPS_PATH}/play`)
    },
    [navigate, showLesson],
  )

  // Greet once on entry.
  useEffect(() => {
    stopSubjectSelection()
    say('Pick a move and I will show you how to do it. Then try it in front of the camera!', [
      ...GESTURES.map((g) => g.label),
      CHIP_PLAY,
    ])
    return () => {
      killSpeech()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // In a lesson, cheer when the camera sees the child make the move they picked.
  const cheeredRef = useRef<GestureId | null>(null)
  useEffect(() => {
    cheeredRef.current = null
  }, [lesson])
  useEffect(() => {
    if (!lesson || detected !== lesson || cheeredRef.current === lesson) return
    const t = setTimeout(() => {
      cheeredRef.current = lesson
      say(`That's it, that's ${GESTURE_BY_ID[lesson].label}! Great job!`, undefined, `Great job! That's ${GESTURE_BY_ID[lesson].label}!`)
    }, MATCH_HOLD_MS)
    return () => clearTimeout(t)
  }, [lesson, detected, say])

  const lessonDef = lesson ? GESTURE_BY_ID[lesson] : null
  const lessonMatched = lesson !== null && detected === lesson
  const readiness = followReadiness(trackingLost ? [] : bodyLandmarks)

  return (
    <div className="rd-root">
      <RpsTopbar />

      <main className="rd-main">
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
            {scores && (
              <div className="rps-scores">
                {GESTURES.map((g) => (
                  <span key={g.id} className={detected === g.id ? 'hit' : ''}>
                    {g.label} {Math.round(scores[g.id] * 100)}%
                  </span>
                ))}
              </div>
            )}
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

        <div className="rd-right-panel">
          {lessonDef && (
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
    </div>
  )
}
