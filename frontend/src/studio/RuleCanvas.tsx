import { useEffect, useState } from 'react'

type NamedItem = { id: string; name: string; thumbnail_svg?: string }
type RuleItem = {
  id?: string
  human_pose_id: string
  sequence_id: string
  robot_pose_id?: string
  enabled?: boolean
}

export function RuleCanvas({
  humanPoses,
  robotPoses,
  rules,
  onCreateRule,
  onPreviewRobotPose,
  onDeleteRule = () => undefined,
  onReorderRules = () => undefined,
  previewBusy = false,
  createBusy = false,
}: {
  humanPoses: NamedItem[]
  robotPoses: NamedItem[]
  rules: RuleItem[]
  onCreateRule: (rule: {
    humanPoseId: string
    robotPoseId: string
    cooldownSeconds: number
  }) => void | Promise<void>
  onPreviewRobotPose: (robotPoseId: string) => void
  onDeleteRule?: (ruleId: string) => void | Promise<void>
  onReorderRules?: (ruleIds: string[]) => void | Promise<void>
  previewBusy?: boolean
  createBusy?: boolean
}) {
  const [humanPoseId, setHumanPoseId] = useState(humanPoses[0]?.id ?? '')
  const [robotPoseId, setRobotPoseId] = useState(robotPoses[0]?.id ?? '')
  const [cooldownSeconds, setCooldownSeconds] = useState(2)
  const [draggedRuleId, setDraggedRuleId] = useState<string | null>(null)
  const canCreate = Boolean(humanPoseId && robotPoseId && cooldownSeconds >= 0)
  const humanPose = (id: string) => humanPoses.find((pose) => pose.id === id)
  const humanName = (id: string) => humanPose(id)?.name ?? 'Unknown pose'
  const robotPoseName = (id?: string) => (
    robotPoses.find((pose) => pose.id === id)?.name ?? 'Unknown robot pose'
  )
  const ruleIds = rules.flatMap((rule) => rule.id ? [rule.id] : [])

  const moveRule = (fromIndex: number, toIndex: number) => {
    if (fromIndex === toIndex || fromIndex < 0 || toIndex < 0) return
    const nextIds = [...ruleIds]
    const [movedId] = nextIds.splice(fromIndex, 1)
    nextIds.splice(toIndex, 0, movedId)
    void onReorderRules(nextIds)
  }

  useEffect(() => {
    if (!humanPoses.some((pose) => pose.id === humanPoseId)) {
      setHumanPoseId(humanPoses[0]?.id ?? '')
    }
  }, [humanPoseId, humanPoses])

  useEffect(() => {
    if (!robotPoses.some((pose) => pose.id === robotPoseId)) {
      setRobotPoseId(robotPoses[0]?.id ?? '')
    }
  }, [robotPoseId, robotPoses])

  return (
    <section className="rule-canvas" aria-labelledby="rule-canvas-title">
      <header className="studio-panel-heading">
        <div>
          <span className="studio-kicker">Human trigger → robot response</span>
          <h2 id="rule-canvas-title">Interaction Sequencer</h2>
        </div>
      </header>
      <div className="rule-list">
        {rules.map((rule, index) => (
          <div
            className="interaction-row"
            key={rule.id ?? `${rule.human_pose_id}-${rule.sequence_id}-${index}`}
            data-testid={rule.id ? `interaction-${rule.id}` : undefined}
            onDragOver={(event) => event.preventDefault()}
            onDrop={() => {
              if (!draggedRuleId || !rule.id) return
              moveRule(ruleIds.indexOf(draggedRuleId), ruleIds.indexOf(rule.id))
              setDraggedRuleId(null)
            }}
          >
            <span className="interaction-number" aria-label={`Interaction ${index + 1}`}>{index + 1}</span>
            <div className="interaction-human">
              <PoseThumbnail pose={humanPose(rule.human_pose_id)} name={humanName(rule.human_pose_id)} />
              <span><small>Human</small><strong>{humanName(rule.human_pose_id)}</strong></span>
            </div>
            <span className="interaction-arrow" aria-hidden="true">→</span>
            <button
              type="button"
              className="interaction-robot"
              aria-label={`Play CoRAL response ${robotPoseName(rule.robot_pose_id)}`}
              disabled={previewBusy || !rule.robot_pose_id}
              onClick={() => rule.robot_pose_id && onPreviewRobotPose(rule.robot_pose_id)}
            >
              <CoralIcon />
              <span><small>CoRAL pose</small><strong>{robotPoseName(rule.robot_pose_id)}</strong></span>
              <i aria-hidden="true">▶</i>
            </button>
            <div className="interaction-controls">
              <button
                type="button"
                className="interaction-drag-handle"
                draggable={Boolean(rule.id)}
                aria-label={`Drag interaction ${index + 1}`}
                disabled={createBusy || !rule.id}
                onDragStart={() => setDraggedRuleId(rule.id ?? null)}
                onDragEnd={() => setDraggedRuleId(null)}
              >⋮⋮</button>
              <button
                type="button"
                aria-label={`Move interaction ${index + 1} up`}
                disabled={createBusy || index === 0 || !rule.id}
                onClick={() => moveRule(index, index - 1)}
              >↑</button>
              <button
                type="button"
                aria-label={`Move interaction ${index + 1} down`}
                disabled={createBusy || index === rules.length - 1 || !rule.id}
                onClick={() => moveRule(index, index + 1)}
              >↓</button>
              <button
                type="button"
                className="interaction-delete"
                aria-label={`Delete interaction ${index + 1}`}
                disabled={createBusy || !rule.id}
                onClick={() => {
                  if (rule.id && window.confirm(`Delete interaction ${index + 1}?`)) {
                    void onDeleteRule(rule.id)
                  }
                }}
              >×</button>
            </div>
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
            <select value={robotPoseId} onChange={(event) => setRobotPoseId(event.target.value)} aria-label="Robot pose">
              {robotPoses.map((pose) => <option key={pose.id} value={pose.id}>{pose.name}</option>)}
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
          disabled={!canCreate || createBusy}
          onClick={() => onCreateRule({ humanPoseId, robotPoseId, cooldownSeconds })}
        >
          {createBusy ? 'Adding…' : 'Add Interaction'}
        </button>
      </div>
    </section>
  )
}

function PoseThumbnail({ pose, name }: { pose?: NamedItem; name: string }) {
  const fallback = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><circle cx="32" cy="12" r="7" fill="none" stroke="#173052" stroke-width="3"/><path d="M32 20v19M16 27l16 7 16-7M32 39 21 57M32 39l11 18" fill="none" stroke="#173052" stroke-width="3" stroke-linecap="round"/></svg>'
  const svg = pose?.thumbnail_svg?.trim() || fallback
  return (
    <img
      className="interaction-pose-thumbnail"
      src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`}
      alt={`Human pose ${name}`}
    />
  )
}

function CoralIcon() {
  return (
    <svg className="interaction-coral-icon" viewBox="0 0 64 64" aria-hidden="true">
      <path d="M32 8v7M28 6h8" />
      <rect x="18" y="16" width="28" height="27" rx="9" />
      <circle cx="27" cy="28" r="2" />
      <circle cx="37" cy="28" r="2" />
      <path d="M27 35h10M18 28h-5v13M46 28h5v13M25 43v13M39 43v13" />
    </svg>
  )
}
