import { useEffect, useState } from 'react'

export interface EditableSequenceStep {
  id: string
  robotPoseId: string
  poseName: string
  holdMs: number
  transitionMs: number
}

function SequenceTimingInput({
  value,
  minimum,
  maximum,
  step,
  onCommit,
}: {
  value: number
  minimum: number
  maximum: number
  step: number
  onCommit: (value: number) => void
}) {
  const [draft, setDraft] = useState(String(value))

  useEffect(() => setDraft(String(value)), [value])

  const commit = () => {
    const parsed = Number(draft)
    const next = Number.isFinite(parsed)
      ? Math.min(maximum, Math.max(minimum, Math.round(parsed)))
      : minimum
    setDraft(String(next))
    onCommit(next)
  }

  return (
    <input
      type="number"
      min={minimum}
      max={maximum}
      step={step}
      value={draft}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={commit}
    />
  )
}

export function SequenceEditor({
  steps,
  onChange,
  onRemove,
}: {
  steps: EditableSequenceStep[]
  onChange: (steps: EditableSequenceStep[]) => void
  onRemove?: (id: string) => void
}) {
  const [ordered, setOrdered] = useState(steps)
  const [draggedId, setDraggedId] = useState<string | null>(null)

  useEffect(() => setOrdered(steps), [steps])

  const commit = (next: EditableSequenceStep[]) => {
    setOrdered(next)
    onChange(next)
  }
  const move = (from: number, to: number) => {
    if (to < 0 || to >= ordered.length) return
    const next = [...ordered]
    const [item] = next.splice(from, 1)
    next.splice(to, 0, item)
    commit(next)
  }
  const updateTiming = (id: string, field: 'holdMs' | 'transitionMs', value: number) => {
    commit(ordered.map((step) => (step.id === id ? { ...step, [field]: value } : step)))
  }
  const dropBefore = (targetId: string) => {
    if (!draggedId || draggedId === targetId) return
    const from = ordered.findIndex((step) => step.id === draggedId)
    const to = ordered.findIndex((step) => step.id === targetId)
    move(from, to)
    setDraggedId(null)
  }

  return (
    <fieldset className="sequence-editor">
      <legend>Response sequence</legend>
      {ordered.length === 0 && <p>Drag robot poses here to build a response.</p>}
      <ol>
        {ordered.map((step, index) => (
          <li
            key={step.id}
            draggable
            onDragStart={() => setDraggedId(step.id)}
            onDragOver={(event) => event.preventDefault()}
            onDrop={() => dropBefore(step.id)}
          >
            <span className="sequence-grip" aria-hidden="true">⠿</span>
            <span className="sequence-index">{String(index + 1).padStart(2, '0')}</span>
            <strong>{step.poseName}</strong>
            <label>
              Hold
              <SequenceTimingInput
                value={step.holdMs}
                minimum={100}
                maximum={60_000}
                step={100}
                onCommit={(value) => updateTiming(step.id, 'holdMs', value)}
              />
              <span>ms</span>
            </label>
            <label>
              Transition
              <SequenceTimingInput
                value={step.transitionMs}
                minimum={100}
                maximum={60_000}
                step={50}
                onCommit={(value) => updateTiming(step.id, 'transitionMs', value)}
              />
              <span>ms</span>
            </label>
            <div className="sequence-actions">
              <button type="button" disabled={index === 0} onClick={() => move(index, index - 1)} aria-label={`Move ${step.poseName} up`}>↑</button>
              <button type="button" disabled={index === ordered.length - 1} onClick={() => move(index, index + 1)} aria-label={`Move ${step.poseName} down`}>↓</button>
              {onRemove && <button type="button" onClick={() => onRemove(step.id)} aria-label={`Remove ${step.poseName}`}>×</button>}
            </div>
          </li>
        ))}
      </ol>
    </fieldset>
  )
}
