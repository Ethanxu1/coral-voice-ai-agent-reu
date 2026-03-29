interface JointStates {
  [key: string]: number
}

interface SimulatorControlsProps {
  onCommand: (command: string) => void
  isConnected: boolean
  jointStates: JointStates
}

function SimulatorControls({
  onCommand,
  isConnected,
  jointStates,
}: SimulatorControlsProps) {
  return (
    <>
      <div className="panel">
        <div className="status">
          <span className={`status-dot ${isConnected ? 'connected' : ''}`} />
          {isConnected ? 'Connected to Apollo' : 'Disconnected'}
        </div>
        <h2>Apollo Robot Controls</h2>

        <div className="control-group">
          <h3>Head (Independent)</h3>
          <div className="button-row">
            <button
              className="control-btn"
              onClick={() => onCommand('head_left')}
              disabled={!isConnected}
            >
              Turn Left
            </button>
            <button
              className="control-btn"
              onClick={() => onCommand('head_right')}
              disabled={!isConnected}
            >
              Turn Right
            </button>
            <button
              className="control-btn"
              onClick={() => onCommand('head_up')}
              disabled={!isConnected}
            >
              Look Up
            </button>
            <button
              className="control-btn"
              onClick={() => onCommand('head_down')}
              disabled={!isConnected}
            >
              Look Down
            </button>
          </div>
        </div>

        <div className="control-group">
          <h3>Torso (Separate 3-DOF)</h3>
          <div className="button-row">
            <button
              className="control-btn"
              onClick={() => onCommand('torso_left')}
              disabled={!isConnected}
            >
              Rotate Left
            </button>
            <button
              className="control-btn"
              onClick={() => onCommand('torso_right')}
              disabled={!isConnected}
            >
              Rotate Right
            </button>
            <button
              className="control-btn"
              onClick={() => onCommand('lean_forward')}
              disabled={!isConnected}
            >
              Lean Fwd
            </button>
            <button
              className="control-btn"
              onClick={() => onCommand('lean_backward')}
              disabled={!isConnected}
            >
              Lean Back
            </button>
          </div>
        </div>

        <div className="control-group">
          <h3>Left Arm</h3>
          <div className="button-row">
            <button
              className="control-btn"
              onClick={() => onCommand('left_arm_up')}
              disabled={!isConnected}
            >
              Up
            </button>
            <button
              className="control-btn"
              onClick={() => onCommand('left_arm_down')}
              disabled={!isConnected}
            >
              Down
            </button>
            <button
              className="control-btn"
              onClick={() => onCommand('left_arm_out')}
              disabled={!isConnected}
            >
              Out
            </button>
            <button
              className="control-btn"
              onClick={() => onCommand('left_arm_in')}
              disabled={!isConnected}
            >
              In
            </button>
          </div>
          <div className="button-row" style={{ marginTop: '0.5rem' }}>
            <button
              className="control-btn"
              onClick={() => onCommand('left_elbow_bend')}
              disabled={!isConnected}
            >
              Bend Elbow
            </button>
            <button
              className="control-btn"
              onClick={() => onCommand('left_elbow_extend')}
              disabled={!isConnected}
            >
              Extend Elbow
            </button>
          </div>
        </div>

        <div className="control-group">
          <h3>Right Arm</h3>
          <div className="button-row">
            <button
              className="control-btn"
              onClick={() => onCommand('right_arm_up')}
              disabled={!isConnected}
            >
              Up
            </button>
            <button
              className="control-btn"
              onClick={() => onCommand('right_arm_down')}
              disabled={!isConnected}
            >
              Down
            </button>
            <button
              className="control-btn"
              onClick={() => onCommand('right_arm_out')}
              disabled={!isConnected}
            >
              Out
            </button>
            <button
              className="control-btn"
              onClick={() => onCommand('right_arm_in')}
              disabled={!isConnected}
            >
              In
            </button>
          </div>
          <div className="button-row" style={{ marginTop: '0.5rem' }}>
            <button
              className="control-btn"
              onClick={() => onCommand('right_elbow_bend')}
              disabled={!isConnected}
            >
              Bend Elbow
            </button>
            <button
              className="control-btn"
              onClick={() => onCommand('right_elbow_extend')}
              disabled={!isConnected}
            >
              Extend Elbow
            </button>
          </div>
        </div>

        <div className="control-group">
          <h3>Preset Poses</h3>
          <div className="button-row">
            <button
              className="control-btn preset"
              onClick={() => onCommand('wave')}
              disabled={!isConnected}
            >
              Wave
            </button>
            <button
              className="control-btn preset"
              onClick={() => onCommand('point')}
              disabled={!isConnected}
            >
              Point
            </button>
            <button
              className="control-btn preset"
              onClick={() => onCommand('nod')}
              disabled={!isConnected}
            >
              Nod Yes
            </button>
            <button
              className="control-btn preset"
              onClick={() => onCommand('shake')}
              disabled={!isConnected}
            >
              Shake No
            </button>
          </div>
          <div className="button-row" style={{ marginTop: '0.5rem' }}>
            <button
              className="control-btn preset"
              onClick={() => onCommand('look_around')}
              disabled={!isConnected}
            >
              Look Around
            </button>
            <button
              className="control-btn preset"
              onClick={() => onCommand('reset')}
              disabled={!isConnected}
            >
              Reset
            </button>
          </div>
        </div>
      </div>

      <div className="panel">
        <h2>Joint States</h2>
        <div className="joint-states">
          {Object.entries(jointStates).map(([name, value]) => (
            <div key={name} className="joint-state">
              <span className="joint-name">{name.replace(/_/g, ' ')}</span>
              <span className="joint-value">{value.toFixed(2)}</span>
            </div>
          ))}
        </div>
      </div>
    </>
  )
}

export default SimulatorControls
