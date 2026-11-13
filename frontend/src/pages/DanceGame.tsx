import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import RobotViewer from '../components/RobotViewer'
import { isLiveMode, resetPose } from '../api/robot'
import { stopSubjectSelection } from '../api/vision'
import CornerMenu from '../rps/CornerMenu'
import DanceWorkspace, { type DanceWorkspaceHandle } from '../dance/DanceWorkspace'
import { hasMoves, type Step } from '../dance/blocks'
import { danceMove } from '../dance/poses'
import { loadCustomPoses } from '../poseDesigner/customPoses'
import { playSequence } from '../dance/sequencePlayer'
import PosePreview, { type PoseHover } from '../dance/PosePreview'
import './DanceGame.css'

/** For the grown-up: how the blocks work, from the corner menu. */
function HowToPlay({ live, onClose }: { live: boolean; onClose: () => void }) {
  return (
    <div className="help" onClick={onClose}>
      <div className="help-card" onClick={(e) => e.stopPropagation()}>
        <h2>How to play</h2>
        <ol className="help-steps">
          <li><span>＋</span><p>Press <b>Add move</b> to make a new move with CORAL. It comes back here on the shelf.</p></li>
          <li><span>🧩</span><p>Drag moves from the shelf and snap them under <b>when ▶ Dance! is pressed</b>.</p></li>
          <li><span>🔁</span><p>Put moves inside <b>repeat</b> to do them again and again.</p></li>
          {live ? (
            <li><span>▶</span><p>Press <b>Simulate</b> to watch CORAL on screen, or <b>Execute</b> to make the real robot dance too.</p></li>
          ) : (
            <li><span>▶</span><p>Press <b>Dance!</b> and watch CORAL go.</p></li>
          )}
        </ol>
        <p className="help-note">Grey blocks aren't snapped on, so CORAL skips them. Drag a block back to the shelf to throw it away.</p>
        <button className="big-btn small" onClick={onClose}>OK</button>
      </div>
    </div>
  )
}

export default function DanceGame() {
  const [program, setProgram] = useState<Step[]>([])
  const [isPlaying, setIsPlaying] = useState(false)
  /** The move playing now, and a count so the same move twice in a row pops the bubble again. */
  const [move, setMove] = useState<{ pose: string; n: number } | null>(null)
  const [help, setHelp] = useState(false)
  /** Live mode (./run.sh -live): offer Simulate (sim only) and Execute (sim + physical robot). */
  const [live, setLive] = useState(false)
  const [failed, setFailed] = useState(false)
  /** The move block stick figure under the pointer, previewed in 3D. */
  const [hover, setHover] = useState<PoseHover | null>(null)
  const workspaceRef = useRef<DanceWorkspaceHandle>(null)
  const tokenRef = useRef(0)
  const navigate = useNavigate()

  // Start from a clean stand; on exit, cancel any dance and stand the sim back up.
  useEffect(() => {
    stopSubjectSelection()
    resetPose().catch(() => {})
    isLiveMode().then(setLive).catch(() => {})
    return () => {
      tokenRef.current++
      resetPose().catch(() => {})
    }
  }, [])

  const finish = () => {
    setIsPlaying(false)
    setMove(null)
    workspaceRef.current?.highlight(null)
  }

  /** `toRobot` (Execute) dances on the physical robot as well as the sim. */
  const handlePlay = async (toRobot: boolean) => {
    const token = ++tokenRef.current
    const alive = () => tokenRef.current === token
    setIsPlaying(true)
    setFailed(false)
    try {
      await playSequence(
        program,
        alive,
        (step) => {
          setMove((m) => ({ pose: step.pose, n: (m?.n ?? 0) + 1 }))
          workspaceRef.current?.highlight(step.blockId)
        },
        { toRobot },
      )
    } catch (e) {
      console.warn('dance sequence failed', e)
      if (alive()) setFailed(true)
    } finally {
      if (alive()) finish()
    }
  }

  /** Stops after the move that is gliding now. */
  const handleStop = () => {
    tokenRef.current++
    finish()
  }

  /** Make a new move in the Pose Designer, which comes back here once it's saved. */
  const handleAddMove = () => navigate('/pose-designer', { state: { from: '/dance-game' } })

  const ready = hasMoves(program)
  const pose = move && danceMove(move.pose)
  const bubble = pose
    ? `${pose.emoji} ${pose.label}!`
    : failed
      ? "Oops! I couldn't finish that dance"
      : !ready
        ? loadCustomPoses().length === 0
          ? 'Press + Add move to make my first move'
          : 'Snap some moves on to make me dance'
        : live
          ? 'Press Simulate or Execute to watch me go'
          : 'Press Dance! to watch me go'

  return (
    <div className="dance">
      <header className="top">
        <h1>Make CORAL dance!</h1>
        <CornerMenu onHelp={() => setHelp(true)} menuPath={null} />
      </header>

      <main className="dance-main">
        <section className="code-card">
          <DanceWorkspace ref={workspaceRef} locked={isPlaying} onChange={setProgram} onPoseHover={setHover} onAddMove={handleAddMove} />
        </section>

        <section className="stage">
          <div key={move ? move.n : bubble} className={`bubble ${pose ? 'move' : ''}`}>
            {bubble}
          </div>
          <div className={`robot ${isPlaying ? 'dancing' : ''}`}>
            <div className="floor" />
            <RobotViewer embedded look="stage" />
          </div>
          {isPlaying ? (
            <button className="big-btn stop" onClick={handleStop}>
              ■ Stop
            </button>
          ) : live ? (
            <div className="btn-row">
              <button className="big-btn pair" onClick={() => handlePlay(false)} disabled={!ready}>
                ▶ Simulate
              </button>
              <button className="big-btn pair execute" onClick={() => handlePlay(true)} disabled={!ready}>
                🤖 Execute
              </button>
            </div>
          ) : (
            <button className="big-btn" onClick={() => handlePlay(false)} disabled={!ready}>
              ▶ Dance!
            </button>
          )}
        </section>
      </main>

      <PosePreview hover={hover} />
      {help && <HowToPlay live={live} onClose={() => setHelp(false)} />}
    </div>
  )
}
