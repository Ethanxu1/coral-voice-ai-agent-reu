import { useEffect } from 'react'
import { setAngleArcsEnabled, setFallCheckEnabled, setMujocoViewerOnLaunch } from '../demo/api'
import { setRobotConfig, useRobotConfig, type LegMode } from '../demo/robotConfig'

const LEG_MODES: { id: LegMode; label: string }[] = [
  { id: 'retarget', label: 'Retarget' },
  { id: 'legacy', label: 'Legacy' },
  { id: 'classify', label: 'Classify' },
  { id: 'buckets', label: 'Buckets' },
]

/** Choose whether pose moves drive only the simulator or both targets. */
export default function RobotModeToggle() {
  const { simOnly, legMode, showAngleArcs, fallCheckEnabled, mujocoViewerOnLaunch } =
    useRobotConfig()

  const selectSimOnly = (next: boolean) => setRobotConfig({ simOnly: next })
  const selectLegMode = (next: LegMode) => setRobotConfig({ legMode: next })
  const toggleAngleArcs = () => setRobotConfig({ showAngleArcs: !showAngleArcs })
  const toggleFallCheck = () => setRobotConfig({ fallCheckEnabled: !fallCheckEnabled })
  const toggleMujocoViewer = () =>
    setRobotConfig({ mujocoViewerOnLaunch: !mujocoViewerOnLaunch })
  // Re-apply the persisted setting to the vision/robot servers whenever it
  // changes, and once on mount — the flags live in the server processes'
  // memory (not disk), so a server restart or a fresh page load would
  // otherwise leave the server out of sync with the UI's remembered state.
  useEffect(() => {
    setAngleArcsEnabled(showAngleArcs)
  }, [showAngleArcs])
  useEffect(() => {
    setFallCheckEnabled(fallCheckEnabled)
  }, [fallCheckEnabled])
  // Same sync, except the server only reads this one at startup — pushing it on
  // every load is what makes the toggle's remembered state the one used next launch.
  useEffect(() => {
    setMujocoViewerOnLaunch(mujocoViewerOnLaunch)
  }, [mujocoViewerOnLaunch])

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
      <div className="robot-mode-legmode">
        <label>Fall check</label>
        <div className="robot-mode-switch">
          <button
            className={`robot-mode-btn ${fallCheckEnabled ? 'active' : ''}`}
            onClick={toggleFallCheck}
          >
            {fallCheckEnabled ? '🛡️ On' : 'Off'}
          </button>
        </div>
      </div>
      <div className="robot-mode-legmode">
        <label>MuJoCo window</label>
        <div className="robot-mode-switch">
          <button
            className={`robot-mode-btn ${mujocoViewerOnLaunch ? 'active' : ''}`}
            onClick={toggleMujocoViewer}
          >
            {mujocoViewerOnLaunch ? '🪟 On' : 'Off'}
          </button>
        </div>
        <span className="robot-mode-hint">applies on next server launch</span>
      </div>
    </div>
  )
}
