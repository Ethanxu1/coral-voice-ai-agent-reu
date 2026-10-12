import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { LiveStream } from './DummyStream'
import RobotViewer from '../components/RobotViewer'
import { usePoseWebSocket } from '../hooks/usePoseWebSocket'
import { getJointPulses, killSpeech, speak, stopSubjectSelection } from '../demo/api'
import { poseSimilarity, type PoseVector } from '../pose/poseSimilarity'
import GestureFigure from '../rps/GestureFigure'
import SkeletonView, { followReadiness } from '../rps/SkeletonView'
import { useRobotFollow } from '../rps/useRobotFollow'
import { useRobotSettle } from '../rps/useRobotSettle'
import { DETECTION, ROBOT_REST_PULSES, figureFromPose } from '../rps/gestures'
import GestureTopbar, { GESTURES_PATH } from '../gestures/GestureTopbar'
import { armPulses } from '../gestures/armJoints'
import { addGesture, downloadJson, nextDefaultName, updateGesture, useGestures } from '../gestures/library'
import { HOLD_MS, useHoldStill } from '../gestures/useHoldStill'
import './RefinedDemo.css'
import './RockPaperScissors.css'
import './GestureStudio.css'

type Phase = 'idle' | 'grace' | 'holding' | 'saved'

/** After "Record", time to walk back from the computer before we start watching. */
const GRACE_MS = 3000
/** Pause on the "saved" tick before going back to idle. */
const SAVED_MS = 2000
/** A recorded pose at least this similar to arms hanging down is not a gesture. */
const REST_SIMILARITY = 0.8
/** If every arm joint is within this many pulses of the stand, the robot didn't copy the gesture. */
const ROBOT_STILL_PULSES = 25

/** Arms hanging by the sides, the pose a person stands in before making a gesture. */
const ARMS_DOWN: PoseVector = {
  leftElbow: [0.6, 0.8],
  leftWrist: [0.65, 1.55],
  rightElbow: [-0.6, 0.8],
  rightWrist: [-0.65, 1.55],
}

const HOLD_OPTS = { minVisibility: DETECTION.minVisibility }

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))

function say(text: string) {
  killSpeech()
    .then(() => speak({ text }))
    .catch(() => {})
}

/**
 * Gesture Studio, recording: the robot follows the person while they pose.
 * Holding still for HOLD_MS, once the robot has also caught up (the same rule
 * as Rock-Paper-Scissors' custom moves), saves the gesture to the library, both as the
 * person's pose (the stick figure) and as the pose the robot reached copying
 * it (what CORAL does for the gesture, fine-tunable in the library).
 */
export default function GestureRecord() {
  const { bodyLandmarks, trackingLost } = usePoseWebSocket()
  const body = trackingLost ? [] : bodyLandmarks
  const readiness = followReadiness(body)
  const following = useRobotFollow()

  const all = useGestures()
  const [name, setName] = useState('')
  const [phase, setPhase] = useState<Phase>('idle')
  const [message, setMessage] = useState<string | null>(null)
  const [warning, setWarning] = useState(false)
  // Gestures recorded on this visit, newest first.
  const [recentIds, setRecentIds] = useState<string[]>([])
  const runIdRef = useRef(0)

  useEffect(() => {
    stopSubjectSelection()
    return () => {
      runIdRef.current++
      killSpeech()
    }
  }, [])

  const startRecording = useCallback(async () => {
    const run = ++runIdRef.current
    setPhase('grace')
    setMessage(null)
    setWarning(false)
    say('Step back, make your gesture, and hold still.')
    await sleep(GRACE_MS)
    if (run !== runIdRef.current) return
    setPhase('holding')
  }, [])

  const cancel = () => {
    runIdRef.current++
    setPhase('idle')
    setMessage(null)
  }

  const save = useCallback(
    async (pose: PoseVector, robotAverage?: Record<string, number> | null) => {
      if (poseSimilarity(pose, ARMS_DOWN, { cameraMayBeMirrored: true }) >= REST_SIMILARITY) {
        setMessage('That looks like arms down. Make a gesture with your arms, then hold still.')
        setWarning(true)
        return
      }
      const run = ++runIdRef.current
      // Stop watching right away so the same hold can't save twice.
      setPhase('saved')
      let robotPulses: Record<string, number>
      let note: string | null = null
      try {
        // The robot's pose averaged over the last moment smooths its follow wobble.
        robotPulses = { ...ROBOT_REST_PULSES, ...armPulses(robotAverage ?? (await getJointPulses())) }
        const copied = Object.keys(ROBOT_REST_PULSES).some(
          (j) => Math.abs(robotPulses[j] - ROBOT_REST_PULSES[j]) >= ROBOT_STILL_PULSES,
        )
        if (!copied) note = "Saved, but CORAL didn't copy it. Set CORAL's pose in the library."
      } catch (e) {
        console.warn('reading robot pose failed', e)
        robotPulses = { ...ROBOT_REST_PULSES }
        note = "Saved, but I couldn't read CORAL's pose (is the simulator running?). Set it in the library."
      }
      if (run !== runIdRef.current) return
      const gesture = addGesture(name, pose, robotPulses)
      setRecentIds((ids) => [gesture.id, ...ids])
      setName('')
      setMessage(note ?? `Saved "${gesture.name}".`)
      setWarning(note !== null)
      say(`Got it! Saved ${gesture.name}.`)
      await sleep(SAVED_MS)
      if (run !== runIdRef.current) return
      setPhase('idle')
    },
    [name],
  )

  // The robot lags the person (gentle follow): wait for it to catch up too.
  const robotSettled = useRobotSettle(phase === 'holding')
  const hold = useHoldStill(
    body,
    phase === 'holding',
    (pose) => save(pose, robotSettled()),
    HOLD_OPTS,
    () => robotSettled() !== null,
  )

  const saveNow = () => {
    const pose = hold.current()
    if (!pose) {
      setMessage("I can't see both arms. Step into the picture first.")
      setWarning(true)
      return
    }
    save(pose)
  }

  const recording = phase === 'grace' || phase === 'holding'
  const recent = recentIds.map((id) => all.find((g) => g.id === id)).filter((g) => g !== undefined)

  let status: string
  if (!following) status = 'Connecting to CORAL… (is the server running?)'
  else if (phase === 'grace') status = 'Get into position and make your gesture…'
  else if (phase === 'holding')
    status = !readiness.ok
      ? readiness.message
      : hold.waiting
      ? 'Keep holding… CORAL is still catching up.'
      : hold.progress > 0 || !message
      ? 'Hold still…'
      : message
  else if (message) status = message
  else status = `Press Record, step back, make a gesture and hold it for ${HOLD_MS / 1000} seconds.`

  return (
    <div className="rd-root">
      <GestureTopbar title="Record gestures" busy={recording} />

      <main className="rd-main">
        <div className="rd-camera-panel rps-quad">
          {/* Controls: name, record, and what was saved on this visit. */}
          <div className="rps-cell gs-panel">
            <div className="rps-cell-title">Record</div>
            <label className="gs-field">
              <span>Gesture name (optional)</span>
              <input
                className="gs-input"
                value={name}
                maxLength={60}
                placeholder={nextDefaultName()}
                onChange={(e) => setName(e.target.value)}
                disabled={phase === 'saved'}
              />
            </label>
            <div className="gs-row">
              {recording ? (
                <>
                  <button className="rps-small-btn" onClick={saveNow} disabled={phase !== 'holding'}>
                    Save now
                  </button>
                  <button className="rps-small-btn gs-ghost" onClick={cancel}>
                    Cancel
                  </button>
                </>
              ) : (
                <button className="rps-big-btn gs-record-btn" disabled={!following || phase === 'saved'} onClick={startRecording}>
                  ● Record
                </button>
              )}
            </div>

            <div className="gs-recent">
              <div className="gs-subhead">Recorded this visit</div>
              {recent.length === 0 && <div className="gs-muted">Nothing yet.</div>}
              {recent.map((g) => (
                <div key={g.id} className="gs-recent-item">
                  <GestureFigure gesture={{ label: g.name, figure: figureFromPose(g.pose) }} />
                  <input
                    className="gs-input gs-input-sm"
                    defaultValue={g.name}
                    maxLength={60}
                    aria-label="Rename gesture"
                    onBlur={(e) => {
                      if (e.target.value.trim() !== g.name) updateGesture(g.id, { name: e.target.value })
                    }}
                    onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
                  />
                </div>
              ))}
            </div>

            <div className="gs-row gs-panel-footer">
              <button className="rps-small-btn" disabled={all.length === 0} onClick={() => downloadJson()}>
                Export all as JSON ({all.length})
              </button>
              <Link to={`${GESTURES_PATH}/library`} className="rps-small-btn gs-ghost gs-link-btn">
                Open library →
              </Link>
            </div>
          </div>

          {/* 1. The robot copying the person: what CORAL will do for the gesture. */}
          <div className="rps-cell">
            <div className="rd-sim-grid" />
            <div className="rd-sim-vignette" />
            <div className="rps-cell-title">1 · Robot simulation</div>
            <RobotViewer embedded />
          </div>

          {/* 2. The camera. */}
          <div className="rps-cell rps-cell-dark">
            <div className="rps-cell-title">2 · Camera</div>
            <LiveStream badge={false} />
          </div>

          {/* 3. The tracker's stick figure and the hold-still progress. */}
          <div className="rps-cell rps-cell-dark">
            <div className="rps-cell-title">3 · Stick figure</div>
            <SkeletonView landmarks={body} />
            {(phase === 'holding' || phase === 'saved') && (
              <div
                className={`rps-hold ${phase === 'saved' ? 'done' : ''}`}
                style={{ ['--p' as string]: phase === 'saved' ? 1 : hold.progress }}
              >
                <span>{phase === 'saved' ? '✓' : `${Math.round(hold.progress * 100)}%`}</span>
              </div>
            )}
            <div className={`rps-note ${warning ? 'warn' : ''}`}>{status}</div>
          </div>
        </div>
      </main>
    </div>
  )
}
