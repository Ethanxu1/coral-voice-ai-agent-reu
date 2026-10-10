import { useEffect, useRef, useState } from 'react'

import RobotViewer from '../components/RobotViewer'
import { visionVideoFeedUrl } from './api'
import { FullBodySkeleton } from './FullBodySkeleton'
import type { Landmark } from './types'

export function LivePreview({
  subjects,
  recognition,
  holds,
  executingSequenceId,
  statusMessage,
  cameraEnabled,
}: {
  subjects: { id: string; landmarks: Landmark[] }[]
  recognition: Record<string, { label: string | null; confidence: number }>
  holds: Record<string, number>
  executingSequenceId: string | null
  statusMessage: string | null
  cameraEnabled: boolean
}) {
  const previewRef = useRef<HTMLElement>(null)
  const [fullscreen, setFullscreen] = useState(false)
  const [fullscreenError, setFullscreenError] = useState<string | null>(null)
  const winner = [...subjects].sort(
    (left, right) => (recognition[right.id]?.confidence ?? 0) - (recognition[left.id]?.confidence ?? 0),
  )[0]
  const winnerRecognition = winner ? recognition[winner.id] : undefined
  const progress = winner ? holds[winner.id] ?? 0 : 0

  useEffect(() => {
    const syncFullscreen = () => setFullscreen(document.fullscreenElement === previewRef.current)
    document.addEventListener('fullscreenchange', syncFullscreen)
    return () => document.removeEventListener('fullscreenchange', syncFullscreen)
  }, [])

  const toggleFullscreen = async () => {
    setFullscreenError(null)
    try {
      if (document.fullscreenElement === previewRef.current) {
        if (!document.exitFullscreen) throw new Error('Fullscreen exit is unavailable')
        await document.exitFullscreen()
      } else {
        if (!previewRef.current?.requestFullscreen) throw new Error('Fullscreen is unavailable')
        await previewRef.current.requestFullscreen()
      }
    } catch {
      setFullscreenError('Fullscreen is not available in this browser')
    }
  }

  return (
    <aside ref={previewRef} className="live-preview" aria-labelledby="live-preview-title">
      <header className="studio-panel-heading">
        <div>
          <span className="studio-kicker">Camera → decision → motion</span>
          <h2 id="live-preview-title">Live Preview</h2>
        </div>
        <div className="preview-heading-actions">
          <span className={`preview-live-dot${winner ? ' is-live' : ''}`}>{winner ? 'Tracking' : 'Waiting'}</span>
          <button
            type="button"
            className="preview-fullscreen-button"
            onClick={() => void toggleFullscreen()}
            aria-label={fullscreen ? 'Exit Live Preview fullscreen' : 'Expand Live Preview'}
          >
            <span aria-hidden="true">{fullscreen ? '↙' : '↗'}</span>
            {fullscreen ? 'Exit Fullscreen' : 'Expand'}
          </button>
        </div>
      </header>
      {fullscreenError ? <p className="preview-fullscreen-error" role="alert">{fullscreenError}</p> : null}

      <section className="preview-stage preview-human-stage">
        <div className="preview-stage-label">Human input</div>
        {cameraEnabled ? (
          <img
            className="preview-camera-feed"
            src={visionVideoFeedUrl}
            alt="Computer camera preview"
          />
        ) : null}
        {!cameraEnabled ? (
          <div className="preview-empty camera-is-off">
            <span className="camera-off-icon" aria-hidden="true">×</span>
            <strong>Computer camera is off</strong>
            <small>Turn it on above to train or recognize a pose.</small>
          </div>
        ) : winner ? (
          <>
            <FullBodySkeleton landmarks={winner.landmarks} label={`Skeleton for ${winner.id}`} />
            <div className="recognition-readout">
              <span>Person {winner.id}</span>
              <strong>{winnerRecognition?.label ?? 'Unknown pose'}</strong>
              <b>{Math.round((winnerRecognition?.confidence ?? 0) * 100)}%</b>
            </div>
          </>
        ) : (
          <div className="preview-empty preview-camera-guidance">
            <span className="preview-reticle" aria-hidden="true" />
            <strong>Step into frame</strong>
            <small>Your full body, including ankles, must be visible.</small>
          </div>
        )}
      </section>

      <div className="hold-meter">
        <div><span>Hold to trigger</span><strong>{Math.round(progress * 100)}%</strong></div>
        <progress
          max={100}
          value={Math.round(progress * 100)}
          aria-label="Pose hold progress"
          aria-valuenow={Math.round(progress * 100)}
        />
        <small>Keep the pose steady for 0.7 seconds.</small>
      </div>

      <section className="preview-stage preview-robot-stage">
        <div className="preview-stage-label">Simulator output</div>
        <RobotViewer embedded />
      </section>

      <div className="safety-strip" role="status">
        <span className="safety-icon" aria-hidden="true">✓</span>
        <div>
          <strong>{executingSequenceId ? 'Sequence running' : 'Simulator safety ready'}</strong>
          <small>{statusMessage ?? 'Every transition is checked before motion.'}</small>
        </div>
      </div>
    </aside>
  )
}
