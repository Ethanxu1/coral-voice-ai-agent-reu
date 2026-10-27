import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { LiveStream } from '../components/LiveStream'
import RobotViewer from '../components/RobotViewer'
import { usePoseWebSocket } from '../hooks/usePoseWebSocket'
import { getJointPulses } from '../api/robot'
import { stopSubjectSelection } from '../api/vision'
import { killSpeech, speak } from '../audio/speech'
import { normalizePose, poseSimilarity, type PoseVector } from '../pose/poseSimilarity'
import GestureFigure from '../rps/GestureFigure'
import SkeletonView, { followReadiness } from '../rps/SkeletonView'
import RpsBar from '../rps/RpsBar'
import { RPS_PATH } from '../rps/RpsTopbar'
import { getCustomMoves, saveCustomMove, tooSimilarPairs } from '../rps/customMoves'
import { customSet } from '../rps/gestureSet'
import { useRobotFollow } from '../rps/useRobotFollow'
import { useRobotSettle } from '../rps/useRobotSettle'
import { DETECTION, GESTURES, GESTURE_BY_ID, ROBOT_REST_PULSES, figureFromPose, type GestureId } from '../rps/gestures'
import './RefinedDemo.css'
import './RockPaperScissors.css'
import './RpsPlay.css'
import { sleep } from '../utils/sleep'

type Phase = 'idle' | 'grace' | 'holding' | 'saved'

/** After "Record", time to walk back from the computer before we start watching. */
const GRACE_MS = 3000
/** Hold the pose this long without moving to record it. */
const STILL_MS = 1500
/** A joint that moves more than this (in shoulder widths) restarts the hold. */
const STILL_TOLERANCE = 0.15
/** Pause after a move is saved before the next one starts by itself. */
const NEXT_MOVE_MS = 2500
/**
 * The robot lags the child (gentle follow), so a move is saved only once the
 * robot has caught up too (useRobotSettle). Save anyway after the child has
 * held this long, in case the robot never quite settles.
 */
const MAX_HOLD_MS = 5000
/** A recorded pose at least this similar to arms hanging down is not a move. */
const REST_SIMILARITY = 0.8
/** If every arm joint is within this many pulses of the stand, the robot didn't copy the move. */
const ROBOT_STILL_PULSES = 25

/** Arms hanging by the sides, the pose a child stands in before making a move. */
const ARMS_DOWN: PoseVector = {
  leftElbow: [0.6, 0.8],
  leftWrist: [0.65, 1.55],
  rightElbow: [-0.6, 0.8],
  rightWrist: [-0.65, 1.55],
}

const ARM_JOINTS = Object.keys(ROBOT_REST_PULSES)

function say(text: string) {
  killSpeech()
    .then(() => speak({ text }))
    .catch(() => {})
}

function meanPose(frames: PoseVector[]): PoseVector {
  const out: PoseVector = {}
  for (const name of Object.keys(frames[0]) as (keyof PoseVector)[]) {
    let x = 0
    let y = 0
    for (const f of frames) {
      x += f[name]![0]
      y += f[name]![1]
    }
    out[name] = [x / frames.length, y / frames.length]
  }
  return out
}

function maxJointDistance(a: PoseVector, b: PoseVector): number {
  let worst = 0
  for (const name of Object.keys(a) as (keyof PoseVector)[]) {
    const pa = a[name]
    const pb = b[name]
    if (pa && pb) worst = Math.max(worst, Math.hypot(pa[0] - pb[0], pa[1] - pb[1]))
  }
  return worst
}

/**
 * "Make your own moves": the child records their own rock, paper and scissors.
 * The robot follows them while they pose, so each move is saved twice: the
 * child's pose (to recognise it in the game) and the pose the robot reached
 * copying it (what CORAL does when it plays that move).
 *
 * Recording is hands-free: after pressing Record, the child steps back and
 * holds still, and the move is saved once they have held it for STILL_MS. A
 * "Save now" button lets a partner save it by hand instead.
 */
export default function RpsCustom() {
  const navigate = useNavigate()
  const { bodyLandmarks, trackingLost } = usePoseWebSocket()
  const body = trackingLost ? [] : bodyLandmarks
  const readiness = followReadiness(body)

  const following = useRobotFollow()

  const [moves, setMoves] = useState(getCustomMoves)
  const [current, setCurrent] = useState<GestureId | null>(null)
  const [phase, setPhase] = useState<Phase>('idle')
  const [progress, setProgress] = useState(0)
  const [message, setMessage] = useState<string | null>(null)

  // Frames of the pose being held, and when the hold began.
  const framesRef = useRef<PoseVector[]>([])
  const stillSinceRef = useRef<number | null>(null)
  const [waitingForRobot, setWaitingForRobot] = useState(false)
  const runIdRef = useRef(0)

  useEffect(() => {
    stopSubjectSelection()
    return () => {
      runIdRef.current++
      killSpeech()
    }
  }, [])

  const startRecording = useCallback(async (id: GestureId) => {
    const run = ++runIdRef.current
    setCurrent(id)
    setPhase('grace')
    setProgress(0)
    setMessage(null)
    framesRef.current = []
    stillSinceRef.current = null
    say(`Show me your ${GESTURE_BY_ID[id].label}. Step back, make your move, and hold still.`)
    await sleep(GRACE_MS)
    if (run !== runIdRef.current) return
    setPhase('holding')
  }, [])

  const save = useCallback(
    async (id: GestureId, pose: PoseVector, robotAverage?: Record<string, number>) => {
      framesRef.current = []
      stillSinceRef.current = null
      if (poseSimilarity(pose, ARMS_DOWN, { cameraMayBeMirrored: true }) >= REST_SIMILARITY) {
        setMessage('That looks like arms down. Make a move with your arms, then hold still.')
        setProgress(0)
        return
      }
      const run = ++runIdRef.current
      // Stop watching right away so the hold can't trigger a second save.
      setPhase('saved')
      setMessage(null)
      let robotPulses: Record<string, number>
      try {
        const all = robotAverage ?? (await getJointPulses())
        robotPulses = Object.fromEntries(ARM_JOINTS.filter((j) => j in all).map((j) => [j, all[j]]))
        if (ARM_JOINTS.every((j) => Math.abs((robotPulses[j] ?? ROBOT_REST_PULSES[j]) - ROBOT_REST_PULSES[j]) < ROBOT_STILL_PULSES)) {
          setMessage("CORAL didn't copy that move. Make sure CORAL is moving with you, then hold still again.")
          setProgress(0)
          setPhase('holding')
          return
        }
      } catch (e) {
        console.warn('reading robot pose failed', e)
        setMessage("I couldn't read the robot's pose. Is the simulator running?")
        setPhase('idle')
        return
      }
      const next = { ...getCustomMoves(), [id]: { pose, robotPulses } }
      if (run !== runIdRef.current) return
      saveCustomMove(id, { pose, robotPulses })
      setMoves(next)
      setProgress(1)
      say(`Got it. That's your ${GESTURE_BY_ID[id].label}.`)

      await sleep(NEXT_MOVE_MS)
      if (run !== runIdRef.current) return
      const missing = GESTURES.find((g) => !next[g.id])
      if (missing) {
        startRecording(missing.id)
      } else {
        setCurrent(null)
        setPhase('idle')
        const clash = tooSimilarPairs(next)
        say(
          clash.length > 0
            ? 'Two of your moves look too alike. Please record one of them again.'
            : 'All three moves are ready. Come back to the computer and press Play.',
        )
      }
    },
    [startRecording],
  )

  // While holding, watch whether the robot has caught up with the child.
  const robotSettled = useRobotSettle(phase === 'holding')
  useEffect(() => {
    if (phase !== 'holding') setWaitingForRobot(false)
  }, [phase])

  // Watch the child hold still and save the move when they have held it long enough.
  useEffect(() => {
    if (phase !== 'holding' || !current) return
    const pose = normalizePose(body, DETECTION)
    const now = Date.now()
    if (!pose) {
      framesRef.current = []
      stillSinceRef.current = null
      setProgress(0)
      return
    }
    const frames = framesRef.current
    if (frames.length === 0 || maxJointDistance(pose, meanPose(frames)) > STILL_TOLERANCE) {
      framesRef.current = [pose]
      stillSinceRef.current = now
      setProgress(0)
      return
    }
    frames.push(pose)
    const held = now - (stillSinceRef.current ?? now)
    setProgress(Math.min(1, held / STILL_MS))
    const robot = robotSettled()
    setWaitingForRobot(held >= STILL_MS && !robot)
    if (held >= STILL_MS && robot) save(current, meanPose(frames), robot)
    else if (held >= MAX_HOLD_MS) save(current, meanPose(frames))
  }, [body, phase, current, save])

  const saveNow = () => {
    if (!current) return
    const pose = framesRef.current.length > 0 ? meanPose(framesRef.current) : normalizePose(body, DETECTION)
    if (!pose) {
      setMessage("I can't see both arms. Step into the picture first.")
      return
    }
    save(current, pose)
  }

  // Stop recording without saving. Picking another move's Record/Redo also
  // switches to it, so a move the camera can't confirm never locks the others.
  const cancelRecording = () => {
    runIdRef.current++
    framesRef.current = []
    stillSinceRef.current = null
    setCurrent(null)
    setPhase('idle')
    setProgress(0)
    setMessage(null)
    killSpeech()
  }

  const clashes = tooSimilarPairs(moves)
  const clashIds = new Set(clashes.flatMap((c) => [c.a, c.b]))
  const allDone = GESTURES.every((g) => moves[g.id])
  const ready = allDone && clashes.length === 0
  const recording = phase === 'grace' || phase === 'holding'

  let status: string
  if (!following) status = 'Connecting to CORAL… (is the server running?)'
  else if (message) status = message
  else if (phase === 'grace' && current) status = `Get into position and make your ${GESTURE_BY_ID[current].label}…`
  else if (phase === 'holding')
    status = !readiness.ok ? readiness.message : waitingForRobot ? 'Keep holding… CORAL is still catching up.' : 'Hold still…'
  else if (phase === 'saved' && current) status = `Got it. That's your ${GESTURE_BY_ID[current].label}.`
  else if (clashes.length > 0)
    status = `${clashes.map((c) => `${GESTURE_BY_ID[c.a].label} and ${GESTURE_BY_ID[c.b].label}`).join(', ')} look too alike. Record one of them again.`
  else if (ready) status = 'All three moves are ready.'
  else status = 'Press Record, step back, make your move and hold still.'

  // Preview of the custom set so the figures match what the game will show.
  const preview = allDone ? customSet(moves as Required<typeof moves>) : null
  const recorded = GESTURES.filter((g) => moves[g.id]).length
  const currentDef = current ? GESTURE_BY_ID[current] : null
  const visible = body.length > 0

  return (
    <div className="rpsp">
      <RpsBar
        actions={
          <button
            className="btn play"
            disabled={!ready || recording}
            onClick={() => navigate(`${RPS_PATH}/play?moves=custom`)}
          >
            Play with my moves →
          </button>
        }
      >
        <div className="round">
          <div className="round-title">Make your own moves</div>
          <div className="pips">
            {GESTURES.map((g) => (
              <span
                key={g.id}
                className={`pip ${clashIds.has(g.id) ? 'lose' : moves[g.id] ? 'win' : current === g.id ? 'now' : ''}`}
              />
            ))}
          </div>
        </div>
      </RpsBar>

      <main className="main">
        {/* CORAL copying the child: this is what CORAL will do for the move. */}
        <section className="panel sim">
          <div className="rd-sim-grid" />
          <RobotViewer embedded />
          <div className="rd-sim-vignette" />
          <div className="panel-head">
            <span className="tag">
              <i />
              CORAL · Copying you
            </span>
          </div>
          {!following && <div className="thinking">Connecting to CORAL… (is the server running?)</div>}
          {phase === 'saved' && currentDef && (
            <div className="played won">
              <span className="em">{currentDef.emoji}</span>Got it. That's your {currentDef.label}
            </div>
          )}
          {phase === 'grace' && currentDef && (
            <div className="count-wrap">
              <div className="modal count-card">
                <div className="kicker">Your own {currentDef.label}</div>
                <div key={current} className="ring" style={{ '--step': `${GRACE_MS}ms` } as React.CSSProperties}>
                  <svg viewBox="0 0 230 230">
                    <circle className="track" cx="115" cy="115" r="100" />
                    <circle className="prog" cx="115" cy="115" r="100" />
                  </svg>
                  <span className="num emoji">{currentDef.emoji}</span>
                </div>
                <h1>Step back</h1>
                <div className="sub">Make your own {currentDef.label} move with your arms, then hold still.</div>
                <div className="pointer">CORAL will copy you</div>
              </div>
            </div>
          )}
        </section>

        <section className={`panel me ${phase === 'grace' ? 'raised' : ''}`}>
          {/* The three moves: record, redo, and see what was saved. */}
          <div className="hint-col">
            <div className="hint-col-title">
              Your moves<small>{recorded} of 3 recorded</small>
            </div>
            {GESTURES.map((g) => {
              const saved = moves[g.id]
              const def = preview?.byId[g.id] ?? (saved ? { ...g, figure: figureFromPose(saved.pose) } : null)
              const active = current === g.id && phase !== 'idle'
              const clash = clashIds.has(g.id)
              let note = saved ? 'Saved' : 'Not recorded yet'
              if (active) note = phase === 'saved' ? 'Saved' : 'Recording…'
              else if (clash) note = 'Too much like another move'
              return (
                <div key={g.id} className={`hint ${active ? 'active' : clash ? 'clash' : saved ? 'match' : ''}`}>
                  <div className="fig">{def ? <GestureFigure gesture={def} /> : <div className="fig-empty">?</div>}</div>
                  <div className="name">
                    {g.label}
                    <span className="em">{g.emoji}</span>
                  </div>
                  <div className="tip">{note}</div>
                  <button
                    className={`rec ${saved ? 'redo' : ''}`}
                    disabled={!following}
                    onClick={() => startRecording(g.id)}
                  >
                    {saved ? 'Redo' : 'Record'}
                  </button>
                </div>
              )
            })}
            {recording && (
              <div className="rec-actions">
                <button className="btn" onClick={saveNow}>
                  Save now
                </button>
                <button className="btn" onClick={cancelRecording}>
                  Cancel
                </button>
              </div>
            )}
          </div>

          {/* The tracker's stick figure, the camera and the hold-still progress. */}
          <div className="skel">
            <div className="panel-head" style={{ left: 16 }}>
              <span className={`tag soft ${readiness.ok ? 'ok' : 'warn'}`}>
                <i />
                {readiness.ok ? 'I can see your head and arms' : visible ? readiness.message : 'Step in front of the camera'}
              </span>
            </div>
            {visible ? (
              <SkeletonView landmarks={body} />
            ) : (
              <div className="skel-empty">
                <div>
                  <b>I can't see you yet</b>Stand where the camera can see your head and arms
                </div>
              </div>
            )}
            {(phase === 'holding' || phase === 'saved') && (
              <div className={`hold-ring ${phase === 'saved' ? 'done' : ''}`}>
                <svg viewBox="0 0 120 120">
                  <circle className="track" cx="60" cy="60" r="50" />
                  <circle className="prog" cx="60" cy="60" r="50" style={{ strokeDashoffset: 314 * (1 - progress) }} />
                </svg>
                <span>{phase === 'saved' ? '✓' : `${Math.round(progress * 100)}%`}</span>
              </div>
            )}
            <div className={`status ${message || clashes.length > 0 ? 'warn' : ''}`}>{status}</div>
            <div className="cam">
              <LiveStream badge={false} />
              <span className="live">
                <i />
                LIVE
              </span>
            </div>
          </div>
        </section>
      </main>

      {phase === 'grace' && <div className="backdrop" />}
    </div>
  )
}
