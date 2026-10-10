// Left panel: the block palette. "Repeat" is a control block — click adds an
// empty loop to the end of the sequence, which the student then drags poses
// (or other Repeat blocks) into. Pose cards below it are the move blocks.

import { DANCE_POSES, type DancePoseId } from './poses'

export default function PoseLibrary({
  onAddPose,
  onAddRepeat,
}: {
  onAddPose: (poseId: DancePoseId) => void
  onAddRepeat: () => void
}) {
  return (
    <div className="dance-library">
      <div className="dance-panel-title">Blocks</div>

      <div className="dance-palette-section-label">Control</div>
      <div className="dance-library-grid">
        <button className="dance-library-card dance-repeat-card" onClick={onAddRepeat}>
          <span className="dance-library-emoji">🔁</span>
          <span className="dance-library-label">Repeat</span>
        </button>
      </div>

      <div className="dance-palette-section-label">Poses</div>
      <div className="dance-library-grid">
        {DANCE_POSES.map((p) => (
          <button key={p.id} className="dance-library-card" onClick={() => onAddPose(p.id)}>
            <span className="dance-library-emoji">{p.emoji}</span>
            <span className="dance-library-label">{p.label}</span>
          </button>
        ))}
      </div>
    </div>
  )
}
