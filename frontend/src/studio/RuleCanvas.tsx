import { useState } from 'react'

type NamedItem = { id: string; name: string }
type RuleItem = { id?: string; human_pose_id: string; sequence_id: string; enabled?: boolean }

export function RuleCanvas({
  humanPoses,
  sequences,
  rules,
  onCreateRule,
}: {
  humanPoses: NamedItem[]
  sequences: NamedItem[]
  rules: RuleItem[]
  onCreateRule: (rule: {
    humanPoseId: string
    sequenceId: string
    cooldownSeconds: number
  }) => void
}) {
  const [humanPoseId, setHumanPoseId] = useState(humanPoses[0]?.id ?? '')
  const [sequenceId, setSequenceId] = useState(sequences[0]?.id ?? '')
  const [cooldownSeconds, setCooldownSeconds] = useState(2)
  const canCreate = Boolean(humanPoseId && sequenceId && cooldownSeconds >= 0)
  const humanName = (id: string) => humanPoses.find((pose) => pose.id === id)?.name ?? 'Unknown pose'
  const sequenceName = (id: string) => sequences.find((sequence) => sequence.id === id)?.name ?? 'Unknown sequence'

  return (
    <section className="rule-canvas" aria-labelledby="rule-canvas-title">
      <header className="studio-panel-heading">
        <div>
          <span className="studio-kicker">Behavior logic</span>
          <h2 id="rule-canvas-title">Rule Canvas</h2>
        </div>
      </header>
      <div className="rule-list">
        {rules.map((rule, index) => (
          <div className="rule-flow" key={rule.id ?? `${rule.human_pose_id}-${rule.sequence_id}-${index}`}>
            <div className="rule-node rule-node-if"><span>IF</span><strong>{humanName(rule.human_pose_id)}</strong></div>
            <span className="rule-arrow" aria-hidden="true">→</span>
            <div className="rule-node rule-node-then"><span>THEN</span><strong>{sequenceName(rule.sequence_id)}</strong></div>
          </div>
        ))}
      </div>
      <div className="rule-composer">
        <div className="rule-node rule-node-if">
          <label>
            <span>IF</span>
            <select value={humanPoseId} onChange={(event) => setHumanPoseId(event.target.value)} aria-label="Human pose">
              {humanPoses.map((pose) => <option key={pose.id} value={pose.id}>{pose.name}</option>)}
            </select>
          </label>
        </div>
        <span className="rule-arrow" aria-hidden="true">→</span>
        <div className="rule-node rule-node-then">
          <label>
            <span>THEN</span>
            <select value={sequenceId} onChange={(event) => setSequenceId(event.target.value)} aria-label="Response sequence">
              {sequences.map((sequence) => <option key={sequence.id} value={sequence.id}>{sequence.name}</option>)}
            </select>
          </label>
        </div>
        <label className="cooldown-field">
          Cooldown
          <input
            type="number"
            min="0"
            step="0.5"
            value={cooldownSeconds}
            onChange={(event) => setCooldownSeconds(Math.max(0, Number(event.target.value)))}
          />
          s
        </label>
        <button
          type="button"
          className="studio-primary-button"
          disabled={!canCreate}
          onClick={() => onCreateRule({ humanPoseId, sequenceId, cooldownSeconds })}
        >
          Add rule
        </button>
      </div>
    </section>
  )
}
