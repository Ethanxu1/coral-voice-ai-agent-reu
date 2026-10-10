import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ConnectionHealthDot } from './RefinedDemo'
import RobotViewer from '../components/RobotViewer'
import { useConnectionStatus } from '../components/ConnectionStatus'
import { resetPose, stopSubjectSelection } from '../demo/api'
import { resetToStand } from '../pose/robotPose'
import { STAND_PULSES, SPEED_CYCLE, type DancePoseId } from '../dance/poses'
import { newPoseBlock, newRepeatBlock, removeBlock, mapBlock, moveBlock, type Block } from '../dance/blocks'
import { playSequence } from '../dance/sequencePlayer'
import PoseLibrary from '../dance/PoseLibrary'
import SequenceBuilder from '../dance/SequenceBuilder'
import './RefinedDemo.css'
import './DanceGame.css'

export default function DanceGame() {
  const navigate = useNavigate()
  const services = useConnectionStatus()

  const [blocks, setBlocks] = useState<Block[]>([])
  const [isPlaying, setIsPlaying] = useState(false)
  const [activeUid, setActiveUid] = useState<string | null>(null)
  const blocksRef = useRef<Block[]>([])
  blocksRef.current = blocks
  const tokenRef = useRef(0)

  // Greet with a clean stand on entry; cancel any in-flight play and settle
  // the sim back to stand on exit.
  useEffect(() => {
    stopSubjectSelection()
    resetToStand(STAND_PULSES).catch(() => {})
    return () => {
      tokenRef.current++
      resetPose().catch(() => {})
    }
  }, [])

  const addPose = useCallback((poseId: DancePoseId) => {
    setBlocks((b) => [...b, newPoseBlock(poseId)])
  }, [])

  const addRepeat = useCallback(() => {
    setBlocks((b) => [...b, newRepeatBlock()])
  }, [])

  const removeBlockByUid = useCallback((uid: string) => {
    setBlocks((b) => removeBlock(b, uid).tree)
  }, [])

  const cycleSpeed = useCallback((uid: string) => {
    setBlocks((b) =>
      mapBlock(b, uid, (blk) =>
        blk.type === 'pose'
          ? { ...blk, speed: SPEED_CYCLE[(SPEED_CYCLE.indexOf(blk.speed) + 1) % SPEED_CYCLE.length] }
          : blk,
      ),
    )
  }, [])

  const setRepeatCount = useCallback((uid: string, n: number) => {
    setBlocks((b) => mapBlock(b, uid, (blk) => (blk.type === 'repeat' ? { ...blk, count: n } : blk)))
  }, [])

  const dropBefore = useCallback((sourceUid: string, destParentUid: string | null, beforeUid: string | null) => {
    setBlocks((b) => moveBlock(b, sourceUid, destParentUid, beforeUid))
  }, [])

  const handlePlay = useCallback(async () => {
    const token = ++tokenRef.current
    setIsPlaying(true)
    setActiveUid(null)
    try {
      await playSequence(
        blocksRef.current,
        () => tokenRef.current === token,
        (uid) => setActiveUid(uid),
      )
    } catch (e) {
      console.warn('dance sequence failed', e)
    } finally {
      if (tokenRef.current === token) {
        setIsPlaying(false)
        setActiveUid(null)
      }
    }
  }, [])

  const handleStop = useCallback(() => {
    tokenRef.current++
    setIsPlaying(false)
    setActiveUid(null)
  }, [])

  const leave = () => navigate('/')

  return (
    <div className="rd-root">
      <header className="rd-topbar">
        <div className="rd-topbar-left">
          <div className="rd-logo">
            coral<span>.</span>
          </div>
        </div>
        <div className="rd-topbar-right">
          <button
            className="rd-topbar-btn ghost"
            onClick={() => {
              resetToStand(STAND_PULSES).catch(() => {})
            }}
          >
            Return to stand
          </button>
          <ConnectionHealthDot services={services} />
          <button className="rd-topbar-btn danger" onClick={leave}>
            End
          </button>
        </div>
      </header>

      <main className="dance-main">
        <PoseLibrary onAddPose={addPose} onAddRepeat={addRepeat} />

        <div className="dance-viewer-col">
          <div className="rd-sim-grid" />
          <div className="rd-sim-vignette" />
          <div className="rd-sim-badge"><span className="rd-sim-badge-dot" />SIM</div>
          <RobotViewer embedded />
        </div>

        <SequenceBuilder
          blocks={blocks}
          isPlaying={isPlaying}
          activeUid={activeUid}
          onDropBefore={dropBefore}
          onRemove={removeBlockByUid}
          onCycleSpeed={cycleSpeed}
          onRepeatCountChange={setRepeatCount}
          onPlay={handlePlay}
          onStop={handleStop}
        />
      </main>
    </div>
  )
}
