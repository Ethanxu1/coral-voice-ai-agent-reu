import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import RobotViewer from '../components/RobotViewer'
import { isLiveMode, resetPose } from '../api/robot'
import { stopSubjectSelection } from '../api/vision'
import CornerMenu from '../rps/CornerMenu'
import DanceWorkspace, { type DanceWorkspaceHandle } from '../dance/DanceWorkspace'
import { hasMoves, type Step } from '../dance/blocks'
import { danceMove } from '../dance/poses'
import { loadCustomPoses, deleteCustomPose, type CustomPose } from '../poseDesigner/customPoses'
import { loadPoseIcons } from '../dance/skeleton'
import { playSequence } from '../dance/sequencePlayer'
import PosePreview, { type PoseHover } from '../dance/PosePreview'
import {
  exportMoves,
  exportProgram,
  importMovesFromFile,
  parseProgramFile,
  finalizeProgramImport,
  type ProgramImportData,
} from '../dance/importExport'
import './DanceGame.css'

function ManageMoves({ onDelete, onClose }: { onDelete: (id: string) => void; onClose: () => void }) {
  const [poses, setPoses] = useState(loadCustomPoses)
  const handleDelete = (p: CustomPose) => {
    if (!confirm(`Delete "${p.name}"? Blocks using it will show "?".`)) return
    onDelete(p.id)
    setPoses(loadCustomPoses())
  }
  return (
    <div className="help" onClick={onClose}>
      <div className="help-card manage-card" onClick={(e) => e.stopPropagation()}>
        <h2>Manage Moves</h2>
        {poses.length === 0 ? (
          <p className="help-note">No moves yet. Use + Add move to make one.</p>
        ) : (
          <ul className="manage-list">
            {poses.map((p) => (
              <li key={p.id}>
                <span className="manage-name">{p.name}</span>
                <button className="manage-del" onClick={() => handleDelete(p)}>Delete</button>
              </li>
            ))}
          </ul>
        )}
        <button className="big-btn small" onClick={onClose}>Close</button>
      </div>
    </div>
  )
}

function MissingMovesDialog({ data, onConfirm, onCancel }: { data: ProgramImportData; onConfirm: () => void; onCancel: () => void }) {
  return (
    <div className="help" onClick={onCancel}>
      <div className="help-card manage-card" onClick={(e) => e.stopPropagation()}>
        <h2>Missing Moves</h2>
        <p className="help-note">This program uses moves you don't have yet:</p>
        <ul className="manage-list">
          {data.missing.map((m) => (
            <li key={m.originalId}>
              <span className="manage-name">{m.name}</span>
            </li>
          ))}
        </ul>
        <p className="help-note">Import them to load this program?</p>
        <div className="dialog-btns">
          <button className="big-btn small" onClick={onConfirm}>Import & Load</button>
          <button className="big-btn small cancel" onClick={onCancel}>Cancel</button>
        </div>
      </div>
    </div>
  )
}

function ToolMenu({ children, open, onToggle }: { children: React.ReactNode; open: boolean; onToggle: () => void }) {
  return (
    <div className="tool-menu">
      <button className="tool-toggle" onClick={onToggle} title="Tools">
        <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden>
          <rect y="2" width="20" height="2.5" rx="1" fill="currentColor" />
          <rect y="8.5" width="20" height="2.5" rx="1" fill="currentColor" />
          <rect y="15" width="20" height="2.5" rx="1" fill="currentColor" />
        </svg>
      </button>
      {open && <div className="tool-pop">{children}</div>}
    </div>
  )
}

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
  const [move, setMove] = useState<{ pose: string; n: number } | null>(null)
  const [help, setHelp] = useState(false)
  const [live, setLive] = useState(false)
  const [failed, setFailed] = useState(false)
  const [hover, setHover] = useState<PoseHover | null>(null)
  const [toolOpen, setToolOpen] = useState(false)
  const [manage, setManage] = useState(false)
  const [pendingImport, setPendingImport] = useState<ProgramImportData | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const workspaceRef = useRef<DanceWorkspaceHandle>(null)
  const tokenRef = useRef(0)
  const navigate = useNavigate()

  const showToast = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(null), 3000)
  }

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

  const handleStop = () => {
    tokenRef.current++
    finish()
  }

  const handleAddMove = () => navigate('/pose-designer', { state: { from: '/dance-game' } })

  const refreshAfterPoseChange = async () => {
    await loadPoseIcons()
    workspaceRef.current?.refreshToolbox()
  }

  const handleDeleteMove = async (id: string) => {
    deleteCustomPose(id)
    await refreshAfterPoseChange()
  }

  const handleExportMoves = () => {
    setToolOpen(false)
    try {
      exportMoves()
    } catch {
      showToast('No moves to export')
    }
  }

  const handleImportMoves = async () => {
    setToolOpen(false)
    try {
      const result = await importMovesFromFile()
      if (!result) return
      await refreshAfterPoseChange()
      showToast(result.imported > 0 ? `Imported ${result.imported} move${result.imported > 1 ? 's' : ''}${result.skipped > 0 ? ` (${result.skipped} already existed)` : ''}` : 'All moves already exist')
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Import failed')
    }
  }

  const handleExportProgram = () => {
    setToolOpen(false)
    const state = workspaceRef.current?.serializeWorkspace()
    if (!state) return
    exportProgram(state)
  }

  const handleImportProgram = async () => {
    setToolOpen(false)
    try {
      const data = await parseProgramFile()
      if (!data) return
      if (data.missing.length > 0) {
        setPendingImport(data)
      } else {
        loadProgram(data)
      }
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Import failed')
    }
  }

  const loadProgram = async (data: ProgramImportData) => {
    const remapped = finalizeProgramImport(data)
    await refreshAfterPoseChange()
    workspaceRef.current?.loadWorkspace(remapped)
    showToast('Program loaded')
  }

  const confirmProgramImport = async () => {
    if (!pendingImport) return
    const data = pendingImport
    setPendingImport(null)
    await loadProgram(data)
  }

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
          <ToolMenu open={toolOpen} onToggle={() => setToolOpen((o) => !o)}>
            <button className="tool-item" onClick={() => { setToolOpen(false); setManage(true) }}>Manage Moves</button>
            <hr className="tool-sep" />
            <button className="tool-item" onClick={handleImportMoves}>Import Moves</button>
            <button className="tool-item" onClick={handleExportMoves}>Export Moves</button>
            <hr className="tool-sep" />
            <button className="tool-item" onClick={handleImportProgram}>Import Program</button>
            <button className="tool-item" onClick={handleExportProgram}>Export Program</button>
          </ToolMenu>
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
      {manage && <ManageMoves onDelete={handleDeleteMove} onClose={() => setManage(false)} />}
      {pendingImport && <MissingMovesDialog data={pendingImport} onConfirm={confirmProgramImport} onCancel={() => setPendingImport(null)} />}
      {toast && <div className="dance-toast">{toast}</div>}
    </div>
  )
}
