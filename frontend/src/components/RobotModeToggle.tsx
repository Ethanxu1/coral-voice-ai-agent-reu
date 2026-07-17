import { useEffect, useState } from 'react'
import { setAngleArcsEnabled } from '../demo/api'
import { setRobotConfig, useRobotConfig, type LegMode, type RobotMode } from '../demo/robotConfig'

const LEG_MODES: { id: LegMode; label: string }[] = [
  { id: 'retarget', label: 'Retarget' },
  { id: 'legacy', label: 'Legacy' },
  { id: 'classify', label: 'Classify' },
  { id: 'buckets', label: 'Buckets' },
]

/** Runtime switch between the Mac sim (localhost:8000/8001) and the physical
 * Pi robot (piHost:9000/9001) — no .env edit or dev-server restart required. */
export default function RobotModeToggle() {
  const { mode, piHost, legMode, showAngleArcs } = useRobotConfig()
  const [hostDraft, setHostDraft] = useState(piHost)

  const selectMode = (next: RobotMode) => setRobotConfig({ mode: next })
  const selectLegMode = (next: LegMode) => setRobotConfig({ legMode: next })
  const toggleAngleArcs = () => setRobotConfig({ showAngleArcs: !showAngleArcs })
  const commitHost = () => {
    const trimmed = hostDraft.trim()
    if (trimmed) setRobotConfig({ piHost: trimmed })
  }

  // Re-apply the persisted setting to the vision server whenever it changes,
  // and once on mount — the flag lives in the vision process's memory (not
  // disk), so a vision-server restart or a fresh page load would otherwise
  // leave the server out of sync with the UI's remembered toggle state.
  useEffect(() => {
    setAngleArcsEnabled(showAngleArcs)
  }, [showAngleArcs])

  return (
    <div className="robot-mode-toggle">
      <div className="robot-mode-switch">
        <button
          className={`robot-mode-btn ${mode === 'sim' ? 'active' : ''}`}
          onClick={() => selectMode('sim')}
        >
          🖥️ Simulation
        </button>
        <button
          className={`robot-mode-btn ${mode === 'hardware' ? 'active' : ''}`}
          onClick={() => selectMode('hardware')}
        >
          🤖 Physical Robot
        </button>
      </div>
      {mode === 'hardware' && (
        <div className="robot-mode-host">
          <label htmlFor="pi-host">Pi host</label>
          <input
            id="pi-host"
            value={hostDraft}
            onChange={(e) => setHostDraft(e.target.value)}
            onBlur={commitHost}
            onKeyDown={(e) => { if (e.key === 'Enter') commitHost() }}
            placeholder="192.168.8.219"
          />
        </div>
      )}
      <div className="robot-mode-legmode">
        <label>Legs</label>
        <div className="robot-mode-switch">
          {LEG_MODES.map(({ id, label }) => (
            <button
              key={id}
              className={`robot-mode-btn ${legMode === id ? 'active' : ''}`}
              onClick={() => selectLegMode(id)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <div className="robot-mode-legmode">
        <label>Angle overlay</label>
        <div className="robot-mode-switch">
          <button
            className={`robot-mode-btn ${showAngleArcs ? 'active' : ''}`}
            onClick={toggleAngleArcs}
          >
            {showAngleArcs ? '📐 On' : 'Off'}
          </button>
        </div>
      </div>
    </div>
  )
}
