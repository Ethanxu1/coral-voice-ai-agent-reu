import { useState } from 'react'

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
  onDeleteHumanPose,
  onDeleteRobotPose,
  onPreviewRobotPose,
  onPreviewSequence,
  previewBusy = false,
}: {
  humanPoses: LibraryItem[]
  robotPoses: LibraryItem[]
  sequences: SequenceItem[]
  selectedId?: string | null
  onSelect: (kind: 'human' | 'robot' | 'sequence', id: string) => void
  onTrainHumanPose: () => void
  onCaptureRobotPose: () => void
  onCreateSequence: () => void
  onDeleteHumanPose: (id: string) => void
  onDeleteRobotPose: (id: string) => void
  onPreviewRobotPose: (id: string) => void
  onPreviewSequence: (id: string) => void
  previewBusy?: boolean
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
        collapsible
      >
        {humanPoses.map((pose) => (
          <div className="library-block-row" key={pose.id}>
            <BlockButton
              name={pose.name}
              meta="Learned trigger"
              selected={selectedId === pose.id}
              onClick={() => onSelect('human', pose.id)}
            />
            <ItemAction
              label={`Delete human pose ${pose.name}`}
              symbol="×"
              onClick={() => onDeleteHumanPose(pose.id)}
            />
          </div>
        ))}
      </LibrarySection>
      <LibrarySection
        title="Robot Poses"
        count={robotPoses.length}
        actionLabel="Capture pose"
        onAction={onCaptureRobotPose}
        collapsible
      >
        {robotPoses.map((pose) => (
          <div className="library-block-row" key={pose.id}>
            <BlockButton
              name={pose.name}
              meta="Robot keyframe"
              selected={selectedId === pose.id}
              disabled={previewBusy}
              onClick={() => {
                onSelect('robot', pose.id)
                onPreviewRobotPose(pose.id)
              }}
            />
            <ItemAction
              label={`Delete robot pose ${pose.name}`}
              symbol="×"
              onClick={() => onDeleteRobotPose(pose.id)}
            />
          </div>
        ))}
      </LibrarySection>
      <LibrarySection
        title="Sequences"
        count={sequences.length}
        actionLabel="New sequence"
        onAction={onCreateSequence}
      >
        {sequences.map((sequence) => (
          <div className="library-block-row" key={sequence.id}>
            <BlockButton
              name={sequence.name}
              meta={`${sequence.steps.length} ${sequence.steps.length === 1 ? 'step' : 'steps'}`}
              selected={selectedId === sequence.id}
              onClick={() => onSelect('sequence', sequence.id)}
            />
            <ItemAction
              label={`Play sequence ${sequence.name}`}
              symbol="▶"
              disabled={previewBusy}
              onClick={() => onPreviewSequence(sequence.id)}
            />
          </div>
        ))}
      </LibrarySection>
    </aside>
  )
}

function ItemAction({
  label,
  symbol,
  onClick,
  disabled = false,
}: {
  label: string
  symbol: string
  onClick: () => void
  disabled?: boolean
}) {
  return (
    <button className="library-item-action" type="button" aria-label={label} onClick={onClick} disabled={disabled}>
      {symbol}
    </button>
  )
}

function LibrarySection({
  title,
  count,
  actionLabel,
  onAction,
  children,
  collapsible = false,
}: {
  title: string
  count: number
  actionLabel: string
  onAction: () => void
  children: React.ReactNode
  collapsible?: boolean
}) {
  const [expanded, setExpanded] = useState(true)
  return (
    <section className={`library-section${expanded ? '' : ' is-collapsed'}`}>
      <div className="library-section-title">
        <div><h3>{title}</h3><span>{count}</span></div>
        {collapsible && (
          <button
            type="button"
            className="library-collapse-button"
            aria-label={`${expanded ? 'Collapse' : 'Expand'} ${title}`}
            aria-expanded={expanded}
            onClick={() => setExpanded((current) => !current)}
          >
            <span aria-hidden="true">⌄</span>
          </button>
        )}
      </div>
      {expanded && (
        <>
          <div className="library-blocks">{children}</div>
          <button className="studio-text-button" type="button" onClick={onAction}>
            + {actionLabel}
          </button>
        </>
      )}
    </section>
  )
}

function BlockButton({
  name,
  meta,
  selected,
  onClick,
  disabled = false,
}: {
  name: string
  meta: string
  selected: boolean
  onClick: () => void
  disabled?: boolean
}) {
  return (
    <button
      className={`library-block${selected ? ' is-selected' : ''}`}
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      aria-label={`${name}, ${meta}`}
      disabled={disabled}
    >
      <span className="library-block-mark" aria-hidden="true" />
      <span>
        <strong>{name}</strong>
        <small>{meta}</small>
      </span>
    </button>
  )
}
