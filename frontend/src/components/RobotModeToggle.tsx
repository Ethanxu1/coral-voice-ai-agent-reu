import { useEffect } from 'react'
import { setAngleArcsEnabled } from '../demo/api'
import { setRobotConfig, useRobotConfig, type LegMode } from '../demo/robotConfig'

const LEG_MODES: { id: LegMode; label: string }[] = [
  { id: 'retarget', label: 'Retarget' },
  { id: 'legacy', label: 'Legacy' },
  { id: 'classify', label: 'Classify' },
  { id: 'buckets', label: 'Buckets' },
]

/** Choose whether pose moves drive only the simulator or both targets. */
export default function RobotModeToggle() {
  const { simOnly, legMode, showAngleArcs } = useRobotConfig()

  const selectSimOnly = (next: boolean) => setRobotConfig({ simOnly: next })
  const selectLegMode = (next: LegMode) => setRobotConfig({ legMode: next })
  const toggleAngleArcs = () => setRobotConfig({ showAngleArcs: !showAngleArcs })
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
          className={`robot-mode-btn ${simOnly ? 'active' : ''}`}
          onClick={() => selectSimOnly(true)}
        >
          🖥️ Simulation Only
        </button>
        <button
          className={`robot-mode-btn ${!simOnly ? 'active' : ''}`}
          onClick={() => selectSimOnly(false)}
        >
          🤖 Robot and Simulation
        </button>
      </div>
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
