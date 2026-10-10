type LibraryItem = { id: string; name: string }
type SequenceItem = LibraryItem & { steps: unknown[] }

export function BlockLibrary({
  humanPoses,
  robotPoses,
  sequences,
  selectedId,
  onSelect,
  onTrainHumanPose,
  onCaptureRobotPose,
  onCreateSequence,
}: {
  humanPoses: LibraryItem[]
  robotPoses: LibraryItem[]
  sequences: SequenceItem[]
  selectedId?: string | null
  onSelect: (kind: 'human' | 'robot' | 'sequence', id: string) => void
  onTrainHumanPose: () => void
  onCaptureRobotPose: () => void
  onCreateSequence: () => void
}) {
  return (
    <aside className="studio-library" aria-label="Block Library">
      <header className="studio-panel-heading">
        <div>
          <span className="studio-kicker">Reusable motion</span>
          <h2>Block Library</h2>
        </div>
      </header>
      <LibrarySection
        title="Human Poses"
        count={humanPoses.length}
        actionLabel="Train pose"
        onAction={onTrainHumanPose}
      >
        {humanPoses.map((pose) => (
          <BlockButton
            key={pose.id}
            name={pose.name}
            meta="Learned trigger"
            selected={selectedId === pose.id}
            onClick={() => onSelect('human', pose.id)}
          />
        ))}
      </LibrarySection>
      <LibrarySection
        title="Robot Poses"
        count={robotPoses.length}
        actionLabel="Capture pose"
        onAction={onCaptureRobotPose}
      >
        {robotPoses.map((pose) => (
          <BlockButton
            key={pose.id}
            name={pose.name}
            meta="Robot keyframe"
            selected={selectedId === pose.id}
            onClick={() => onSelect('robot', pose.id)}
          />
        ))}
      </LibrarySection>
      <LibrarySection
        title="Sequences"
        count={sequences.length}
        actionLabel="New sequence"
        onAction={onCreateSequence}
      >
        {sequences.map((sequence) => (
          <BlockButton
            key={sequence.id}
            name={sequence.name}
            meta={`${sequence.steps.length} ${sequence.steps.length === 1 ? 'step' : 'steps'}`}
            selected={selectedId === sequence.id}
            onClick={() => onSelect('sequence', sequence.id)}
          />
        ))}
      </LibrarySection>
    </aside>
  )
}

function LibrarySection({
  title,
  count,
  actionLabel,
  onAction,
  children,
}: {
  title: string
  count: number
  actionLabel: string
  onAction: () => void
  children: React.ReactNode
}) {
  return (
    <section className="library-section">
      <div className="library-section-title">
        <h3>{title}</h3>
        <span>{count}</span>
      </div>
      <div className="library-blocks">{children}</div>
      <button className="studio-text-button" type="button" onClick={onAction}>
        + {actionLabel}
      </button>
    </section>
  )
}

function BlockButton({
  name,
  meta,
  selected,
  onClick,
}: {
  name: string
  meta: string
  selected: boolean
  onClick: () => void
}) {
  return (
    <button
      className={`library-block${selected ? ' is-selected' : ''}`}
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      aria-label={`${name}, ${meta}`}
    >
      <span className="library-block-mark" aria-hidden="true" />
      <span>
        <strong>{name}</strong>
        <small>{meta}</small>
      </span>
    </button>
  )
}
