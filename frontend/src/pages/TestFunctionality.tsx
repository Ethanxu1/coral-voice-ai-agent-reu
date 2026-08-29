import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import RobotViewer from '../components/RobotViewer'
import { getRobotBase, getRobotStream } from '../demo/robotConfig'
import { resetPose } from '../demo/api'
import { ACTION_WS } from '../demo/config'
import './TestFunctionality.css'

const JOINT_GROUPS: {
  title: string
  joints: { label: string; commands: { label: string; cmd: string }[] }[]
}[] = [
  {
    title: 'Head',
    joints: [
      { label: 'Pan', commands: [{ label: '←', cmd: 'head_left' }, { label: '→', cmd: 'head_right' }] },
      { label: 'Tilt', commands: [{ label: '↑', cmd: 'head_up' }, { label: '↓', cmd: 'head_down' }] },
    ],
  },
  {
    title: 'Left Arm',
    joints: [
      { label: 'Shoulder', commands: [{ label: 'Up', cmd: 'left_arm_up' }, { label: 'Down', cmd: 'left_arm_down' }, { label: 'Out', cmd: 'left_arm_out' }, { label: 'In', cmd: 'left_arm_in' }] },
      { label: 'Elbow', commands: [{ label: 'Bend', cmd: 'left_elbow_bend' }, { label: 'Extend', cmd: 'left_elbow_extend' }, { label: 'Rot In', cmd: 'left_elbow_rotate_in' }, { label: 'Rot Out', cmd: 'left_elbow_rotate_out' }] },
      { label: 'Gripper', commands: [{ label: 'Open', cmd: 'left_gripper_open' }, { label: 'Close', cmd: 'left_gripper_close' }] },
    ],
  },
  {
    title: 'Right Arm',
    joints: [
      { label: 'Shoulder', commands: [{ label: 'Up', cmd: 'right_arm_up' }, { label: 'Down', cmd: 'right_arm_down' }, { label: 'Out', cmd: 'right_arm_out' }, { label: 'In', cmd: 'right_arm_in' }] },
      { label: 'Elbow', commands: [{ label: 'Bend', cmd: 'right_elbow_bend' }, { label: 'Extend', cmd: 'right_elbow_extend' }, { label: 'Rot In', cmd: 'right_elbow_rotate_in' }, { label: 'Rot Out', cmd: 'right_elbow_rotate_out' }] },
      { label: 'Gripper', commands: [{ label: 'Open', cmd: 'right_gripper_open' }, { label: 'Close', cmd: 'right_gripper_close' }] },
    ],
  },
  {
    title: 'Left Leg',
    joints: [
      { label: 'Hip', commands: [{ label: 'Fwd', cmd: 'left_hip_forward' }, { label: 'Back', cmd: 'left_hip_backward' }, { label: 'Out', cmd: 'left_hip_out' }, { label: 'In', cmd: 'left_hip_in' }, { label: 'Rot In', cmd: 'left_hip_rotate_in' }, { label: 'Rot Out', cmd: 'left_hip_rotate_out' }] },
      { label: 'Knee', commands: [{ label: 'Bend', cmd: 'left_knee_bend' }, { label: 'Extend', cmd: 'left_knee_extend' }] },
      { label: 'Ankle', commands: [{ label: 'Up', cmd: 'left_ankle_up' }, { label: 'Down', cmd: 'left_ankle_down' }, { label: 'Roll In', cmd: 'left_ankle_roll_in' }, { label: 'Roll Out', cmd: 'left_ankle_roll_out' }] },
    ],
  },
  {
    title: 'Right Leg',
    joints: [
      { label: 'Hip', commands: [{ label: 'Fwd', cmd: 'right_hip_forward' }, { label: 'Back', cmd: 'right_hip_backward' }, { label: 'Out', cmd: 'right_hip_out' }, { label: 'In', cmd: 'right_hip_in' }, { label: 'Rot In', cmd: 'right_hip_rotate_in' }, { label: 'Rot Out', cmd: 'right_hip_rotate_out' }] },
      { label: 'Knee', commands: [{ label: 'Bend', cmd: 'right_knee_bend' }, { label: 'Extend', cmd: 'right_knee_extend' }] },
      { label: 'Ankle', commands: [{ label: 'Up', cmd: 'right_ankle_up' }, { label: 'Down', cmd: 'right_ankle_down' }, { label: 'Roll In', cmd: 'right_ankle_roll_in' }, { label: 'Roll Out', cmd: 'right_ankle_roll_out' }] },
    ],
  },
  {
    title: 'Presets',
    joints: [
      { label: 'Pose', commands: [{ label: 'Wave', cmd: 'wave' }, { label: 'Point', cmd: 'point' }, { label: 'Look', cmd: 'look_around' }, { label: 'Nod', cmd: 'nod' }, { label: 'Shake', cmd: 'shake' }] },
    ],
  },
]

function radToDeg(rad: number): number {
  return (rad * 180) / Math.PI
}

export default function TestFunctionality() {
  const [wsState, setWsState] = useState<'connecting' | 'open' | 'closed' | 'error'>('connecting')
  const [joints, setJoints] = useState<Record<string, number>>({})
  const [lastCmd, setLastCmd] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const cameraKeyRef = useRef(0)

  // WebSocket for commands
  useEffect(() => {
    const ws = new WebSocket(ACTION_WS)
    wsRef.current = ws
    ws.onopen = () => setWsState('open')
    ws.onclose = () => setWsState('closed')
    ws.onerror = () => setWsState('error')
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.type === 'command_result') {
          setLastCmd(`${data.command}: ${data.success ? 'ok' : 'failed'}`)
        }
      } catch {
        /* ignore */
      }
    }
    return () => ws.close()
  }, [])

  // Poll joint states
  useEffect(() => {
    let cancelled = false
    const tick = async () => {
      try {
        const res = await fetch(`${getRobotBase()}/joint_states`, { signal: AbortSignal.timeout(2500) })
        if (!res.ok) return
        const data = await res.json()
        if (!cancelled && data.joint_states) setJoints(data.joint_states)
      } catch {
        /* ignore */
      }
    }
    tick()
    const interval = setInterval(tick, 1000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [])

  const sendCommand = useCallback((cmd: string) => {
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    setLastCmd(`sending ${cmd}…`)
    ws.send(JSON.stringify({ type: 'command', command: cmd }))
  }, [])

  const sortedJoints = Object.entries(joints).sort(([a], [b]) => a.localeCompare(b))

  return (
    <div className="tf-root">
      <header className="tf-header">
        <Link to="/" className="tf-back">← Back</Link>
        <h1 className="tf-title">Test functionality</h1>
        <Link to="/pose-tester" className="tf-link">Open Pose Tester →</Link>
      </header>

      <main className="tf-main">
        <div className="tf-visual-row">
          <div className="tf-panel tf-viewer">
            <div className="tf-panel-header">
              <span>MuJoCo viewer</span>
              <span className={`tf-status tf-status-${wsState}`}>{wsState}</span>
            </div>
            <div className="tf-viewer-wrap">
              <RobotViewer embedded />
            </div>
          </div>

          <div className="tf-panel tf-camera">
            <div className="tf-panel-header">
              <span>Camera</span>
              <span className="tf-camera-hint">{getRobotStream()}/video_feed</span>
            </div>
            <div className="tf-camera-wrap">
              <img
                key={cameraKeyRef.current}
                src={`${getRobotStream()}/video_feed`}
                alt="Live camera"
                onError={() => setTimeout(() => { cameraKeyRef.current += 1 }, 2000)}
              />
              <span className="tf-live-badge">● LIVE</span>
            </div>
          </div>
        </div>

        <div className="tf-controls-row">
          <div className="tf-panel tf-joints">
            <div className="tf-panel-header">
              <span>Joint controls</span>
              {lastCmd && <span className="tf-last-cmd">{lastCmd}</span>}
            </div>
            <div className="tf-joints-scroll">
              {JOINT_GROUPS.map((group) => (
                <div key={group.title} className="tf-group">
                  <div className="tf-group-title">{group.title}</div>
                  {group.joints.map((joint) => (
                    <div key={joint.label} className="tf-joint-row">
                      <span className="tf-joint-label">{joint.label}</span>
                      <div className="tf-joint-buttons">
                        {joint.commands.map((c) => (
                          <button
                            key={c.cmd}
                            className="tf-joint-btn"
                            onClick={() => sendCommand(c.cmd)}
                            disabled={wsState !== 'open'}
                            title={c.cmd}
                          >
                            {c.label}
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              ))}
              <button
                className="tf-joint-btn tf-reset-btn"
                onClick={() => resetPose().catch(() => setLastCmd('reset failed'))}
              >
                Reset to stand
              </button>
            </div>
          </div>

          <div className="tf-panel tf-state">
            <div className="tf-panel-header">
              <span>Current joint positions</span>
              <span className="tf-state-hint">degrees</span>
            </div>
            <div className="tf-state-scroll">
              {sortedJoints.length === 0 ? (
                <div className="tf-empty">No joint state yet</div>
              ) : (
                sortedJoints.map(([name, rad]) => (
                  <div key={name} className="tf-state-row">
                    <span className="tf-state-name">{name}</span>
                    <span className="tf-state-value">{radToDeg(rad).toFixed(1)}°</span>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}
