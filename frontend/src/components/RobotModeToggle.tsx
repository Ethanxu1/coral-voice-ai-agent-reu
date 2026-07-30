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
  // Pushing these settings to the vision/robot servers is useServerSettingsSync's
  // job, mounted at the app root — this component renders on "/" only, so syncing
  // from here left every other route (the refined demo especially) unsynced.

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
