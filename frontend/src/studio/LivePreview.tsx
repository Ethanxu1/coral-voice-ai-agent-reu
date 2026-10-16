import { useEffect, useRef, useState } from 'react'

import RobotViewer from '../components/RobotViewer'
import { visionVideoFeedUrl } from './api'
import { UpperBodySkeleton } from './FullBodySkeleton'
import type { Landmark } from './types'

export function LivePreview({
  subjects,
  recognition,
  poseNamesById = {},
  holds,
  executingSequenceId,
  statusMessage,
  cameraEnabled,
  onResetSimulator,
  simulatorResetting,
}: {
  subjects: { id: string; landmarks: Landmark[] }[]
  recognition: Record<string, { label: string | null; confidence: number; reason?: string }>
  poseNamesById?: Record<string, string>
  holds: Record<string, number>
  executingSequenceId: string | null
  statusMessage: string | null
  cameraEnabled: boolean
  onResetSimulator: () => Promise<boolean>
  simulatorResetting: boolean
}) {
  const previewRef = useRef<HTMLElement>(null)
  const [fullscreen, setFullscreen] = useState(false)
  const [fullscreenError, setFullscreenError] = useState<string | null>(null)
  const winner = [...subjects].sort((left, right) => {
    const leftRecognition = recognition[left.id]
    const rightRecognition = recognition[right.id]
    const recognitionDelta =
      Number(Boolean(rightRecognition?.label)) - Number(Boolean(leftRecognition?.label))

    return (
      recognitionDelta ||
      (rightRecognition?.confidence ?? 0) - (leftRecognition?.confidence ?? 0)
    )
  })[0]
  const winnerRecognition = winner ? recognition[winner.id] : undefined
  const recognizedPoseName = winnerRecognition?.label
    ? poseNamesById[winnerRecognition.label] ?? winnerRecognition.label
    : 'No pose matched'
  const progress = winner ? holds[winner.id] ?? 0 : 0
  const rejectionMessage = !winnerRecognition?.label
    ? recognitionGuidance(winnerRecognition?.reason)
    : null

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
          <button
            type="button"
            className="preview-fullscreen-button"
            disabled={simulatorResetting}
            onClick={() => void onResetSimulator()}
            aria-label="Reset Simulator"
          >
            <span aria-hidden="true">↻</span>
            {simulatorResetting ? 'Resetting…' : 'Reset Simulator'}
          </button>
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
            <UpperBodySkeleton landmarks={winner.landmarks} label={`Skeleton for ${winner.id}`} />
            <div className="recognition-readout">
              <span>Person {winner.id}</span>
              <strong>{recognizedPoseName}</strong>
              <b>{Math.round((winnerRecognition?.confidence ?? 0) * 100)}%</b>
              {rejectionMessage ? <small>{rejectionMessage}</small> : null}
            </div>
          </>
        ) : (
          <div className="preview-empty preview-camera-guidance">
            <span className="preview-reticle" aria-hidden="true" />
            <strong>Step into frame</strong>
            <small>Keep your shoulders, elbows, and wrists visible.</small>
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

function recognitionGuidance(reason?: string): string | null {
  if (reason === 'out_of_distribution') return 'Pose differs from its training examples.'
  if (reason === 'ambiguous') return 'Pose resembles multiple saved poses.'
  if (reason === 'low_visibility') return 'Keep both shoulders, elbows, and wrists visible.'
  if (reason === 'low_confidence') return 'Pose match confidence is too low.'
  if (reason === 'no_samples') return 'Train a Human Pose to begin recognition.'
  return null
}
