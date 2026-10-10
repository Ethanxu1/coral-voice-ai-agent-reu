import RobotViewer from '../components/RobotViewer'
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
  const winner = [...subjects].sort(
    (left, right) => (recognition[right.id]?.confidence ?? 0) - (recognition[left.id]?.confidence ?? 0),
  )[0]
  const winnerRecognition = winner ? recognition[winner.id] : undefined
  const progress = winner ? holds[winner.id] ?? 0 : 0

  return (
    <aside className="live-preview" aria-labelledby="live-preview-title">
      <header className="studio-panel-heading">
        <div>
          <span className="studio-kicker">Camera → decision → motion</span>
          <h2 id="live-preview-title">Live Preview</h2>
        </div>
        <span className={`preview-live-dot${winner ? ' is-live' : ''}`}>{winner ? 'Tracking' : 'Waiting'}</span>
      </header>

      <section className="preview-stage preview-human-stage">
        <div className="preview-stage-label">Human input</div>
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
          <div className="preview-empty">
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
