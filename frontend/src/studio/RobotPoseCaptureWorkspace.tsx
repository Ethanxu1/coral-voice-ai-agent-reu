import { useState } from 'react'

import RobotViewer from '../components/RobotViewer'
import { visionVideoFeedUrl } from './api'

export function RobotPoseCaptureWorkspace({
  open,
  name,
  cameraEnabled,
  onNameChange,
  onCapture,
  onClose,
}: {
  open: boolean
  name: string
  cameraEnabled: boolean
  onNameChange: (name: string) => void
  onCapture: (name: string) => Promise<unknown>
  onClose: () => void
}) {
  const [capturing, setCapturing] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!open) return null

  const capture = async () => {
    if (!name.trim() || capturing) return
    setCapturing(true)
    setError(null)
    try {
      await onCapture(name.trim())
      setSaved(true)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not capture this pose')
    } finally {
      setCapturing(false)
    }
  }

  return (
    <div className="pose-capture-shell">
      <section
        className="pose-capture-workspace"
        role="dialog"
        aria-modal="true"
        aria-labelledby="pose-capture-title"
      >
        <header className="pose-capture-header">
          <div>
            <span className="studio-kicker">Human → safety check → simulator</span>
            <h2 id="pose-capture-title">Pose Capture</h2>
          </div>
          <button
            type="button"
            className="capture-close"
            onClick={onClose}
            disabled={capturing}
            aria-label="Close pose capture"
          >
            ×
          </button>
        </header>

        <div className="pose-capture-stage">
          <section className="capture-viewport capture-human" aria-label="Human pose preview">
            <span className="capture-viewport-label">You</span>
            {cameraEnabled ? (
              <img src={visionVideoFeedUrl} alt="Live human pose" />
            ) : (
              <div className="capture-camera-off">
                <strong>Camera is off</strong>
                <small>Turn on the computer camera before capturing.</small>
              </div>
            )}
          </section>
          <section className="capture-viewport capture-robot" aria-label="Robot pose preview">
            <span className="capture-viewport-label">Robot simulator</span>
            <RobotViewer embedded />
          </section>
        </div>

        <footer className="pose-capture-controls">
          <div className="capture-instruction">
            <strong>{saved ? 'Pose saved and shown in the simulator' : 'Match the pose you want the robot to remember'}</strong>
            <small>{saved ? 'Safety checks passed. Compare both views, then finish.' : 'Keep your full body, knees, and ankles visible.'}</small>
          </div>
          {error ? <p className="capture-error" role="alert">{error}</p> : null}
          <label>
            Robot pose name
            <input
              value={name}
              onChange={(event) => onNameChange(event.target.value)}
              disabled={capturing || saved}
              autoFocus
            />
          </label>
          {saved ? (
            <button type="button" className="studio-primary-button" onClick={onClose}>Done</button>
          ) : (
            <>
              <button
                type="button"
                className="studio-ghost-button"
                onClick={onClose}
                disabled={capturing}
              >
                Cancel
              </button>
              <button
                type="button"
                className="studio-primary-button"
                disabled={!name.trim() || capturing || !cameraEnabled}
                onClick={() => void capture()}
              >
                {capturing ? 'Checking…' : 'Capture & Safety Check'}
              </button>
            </>
          )}
        </footer>
      </section>
    </div>
  )
}
