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
          {isConnected ? 'Connected to AiNex' : 'Disconnected'}
        </div>
        <h2>AiNex Robot Controls</h2>

        <div className="control-group">
          <h3>Head</h3>
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
            <button
              className="control-btn"
              onClick={() => onCommand('left_elbow_rotate_in')}
              disabled={!isConnected}
            >
              Rotate In
            </button>
            <button
              className="control-btn"
              onClick={() => onCommand('left_elbow_rotate_out')}
              disabled={!isConnected}
            >
              Rotate Out
            </button>
          </div>
          <div className="button-row" style={{ marginTop: '0.5rem' }}>
            <button
              className="control-btn"
              onClick={() => onCommand('left_gripper_open')}
              disabled={!isConnected}
            >
              Open Gripper
            </button>
            <button
              className="control-btn"
              onClick={() => onCommand('left_gripper_close')}
              disabled={!isConnected}
            >
              Close Gripper
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
            <button
              className="control-btn"
              onClick={() => onCommand('right_elbow_rotate_in')}
              disabled={!isConnected}
            >
              Rotate In
            </button>
            <button
              className="control-btn"
              onClick={() => onCommand('right_elbow_rotate_out')}
              disabled={!isConnected}
            >
              Rotate Out
            </button>
          </div>
          <div className="button-row" style={{ marginTop: '0.5rem' }}>
            <button
              className="control-btn"
              onClick={() => onCommand('right_gripper_open')}
              disabled={!isConnected}
            >
              Open Gripper
            </button>
            <button
              className="control-btn"
              onClick={() => onCommand('right_gripper_close')}
              disabled={!isConnected}
            >
              Close Gripper
            </button>
          </div>
        </div>

        <div className="button-row" style={{ marginTop: '0.5rem' }}>
          <button
            className="control-btn preset"
            onClick={() => onCommand('reset')}
            disabled={!isConnected}
          >
            Reset Pose
          </button>
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
