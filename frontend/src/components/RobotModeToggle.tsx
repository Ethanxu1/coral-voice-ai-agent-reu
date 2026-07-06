import { useState } from 'react'
import { setRobotConfig, useRobotConfig, type RobotMode } from '../demo/robotConfig'

/** Runtime switch between the Mac sim (localhost:8000/8001) and the physical
 * Pi robot (piHost:9000/9001) — no .env edit or dev-server restart required. */
export default function RobotModeToggle() {
  const { mode, piHost } = useRobotConfig()
  const [hostDraft, setHostDraft] = useState(piHost)

  const selectMode = (next: RobotMode) => setRobotConfig({ mode: next })
  const commitHost = () => {
    const trimmed = hostDraft.trim()
    if (trimmed) setRobotConfig({ piHost: trimmed })
  }

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
    </div>
  )
}
