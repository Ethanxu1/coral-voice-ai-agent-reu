import { useMemo, useState } from 'react'

import { UpperBodySkeleton } from './FullBodySkeleton'
import type { HumanPose, Landmark } from './types'

type TrainingApi = {
  createHumanPose: (payload: {
    project_id: string
    name: string
    min_confidence: number
    hold_seconds: number
  }) => Promise<Pick<HumanPose, 'id'> | { id: string }>
  addHumanPoseSample: (poseId: string, landmarks: Landmark[]) => Promise<unknown>
}

export function PoseTrainingDialog({
  open,
  projectId,
  existingNames,
  subjects,
  api,
  onSaved,
  onClose,
}: {
  open: boolean
  projectId: string
  existingNames: string[]
  subjects: { id: string; landmarks: Landmark[] }[]
  api: TrainingApi
  onSaved: (poseId: string) => void
  onClose: () => void
}) {
  const [name, setName] = useState('')
  const [samples, setSamples] = useState<Landmark[][]>([])
  const [message, setMessage] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const selected = useMemo(
    () => [...subjects].filter((subject) => upperBodyVisible(subject.landmarks)).sort(
      (left, right) => upperBodyVisibility(right.landmarks) - upperBodyVisibility(left.landmarks),
    )[0] ?? [...subjects].sort(
      (left, right) => upperBodyVisibility(right.landmarks) - upperBodyVisibility(left.landmarks),
    )[0],
    [subjects],
  )
  const duplicate = existingNames.some(
    (existing) => existing.trim().toLocaleLowerCase() === name.trim().toLocaleLowerCase(),
  )
  const canSave = name.trim().length > 0 && !duplicate && samples.length >= 3 && !saving
  const sampleMessage = useMemo(
    () => `${samples.length} of 3 required samples accepted`,
    [samples.length],
  )

  if (!open) return null

  const capture = () => {
    if (!selected || !upperBodyVisible(selected.landmarks)) {
      setMessage('Upper body not visible')
      return
    }
    setSamples((current) => [...current, selected.landmarks.map((landmark) => ({ ...landmark }))])
    setMessage('Sample accepted')
  }

  const save = async () => {
    if (!canSave) return
    setSaving(true)
    setMessage(null)
    try {
      const pose = await api.createHumanPose({
        project_id: projectId,
        name: name.trim(),
        min_confidence: 0.78,
        hold_seconds: 0.7,
      })
      await Promise.all(samples.map((sample) => api.addHumanPoseSample(pose.id, sample)))
      onSaved(pose.id)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not save pose')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="studio-dialog-backdrop" role="presentation">
      <section className="studio-dialog" role="dialog" aria-modal="true" aria-labelledby="train-title">
        <header>
          <div>
            <span className="studio-kicker">Few-shot training</span>
            <h2 id="train-title">Train a human pose</h2>
          </div>
          <button type="button" onClick={onClose} aria-label="Close training dialog">×</button>
        </header>
        <div className="training-grid">
          <div className="training-preview">
            {selected ? (
              <UpperBodySkeleton landmarks={selected.landmarks} label="Current upper-body skeleton" />
            ) : (
              <p>No person detected</p>
            )}
          </div>
          <div className="training-controls">
            <label>
              Pose name
              <input value={name} onChange={(event) => setName(event.target.value)} autoFocus />
            </label>
            {duplicate && <p className="field-error">Use a unique pose name</p>}
            <p className="training-tracking-note">The clearest visible upper body is captured automatically.</p>
            <div className="sample-meter" aria-label={sampleMessage}>
              {[0, 1, 2].map((index) => (
                <span key={index} className={samples.length > index ? 'is-filled' : ''} />
              ))}
            </div>
            <p>{sampleMessage}</p>
            {message && <p role="status">{message}</p>}
            <button type="button" className="studio-secondary-button" onClick={capture}>
              Capture sample
            </button>
          </div>
        </div>
        <footer>
          <button type="button" className="studio-ghost-button" onClick={onClose}>Cancel</button>
          <button type="button" className="studio-primary-button" disabled={!canSave} onClick={save}>
            {saving ? 'Saving…' : 'Save human pose'}
          </button>
        </footer>
      </section>
    </div>
  )
}

const UPPER_BODY_JOINTS = [0, 11, 12, 13, 14, 15, 16] as const

function upperBodyVisible(landmarks: Landmark[]): boolean {
  const required = UPPER_BODY_JOINTS
  return required.every((index) => {
    const landmark = landmarks[index]
    return Boolean(
      landmark &&
        Number.isFinite(landmark.x) &&
        Number.isFinite(landmark.y) &&
        landmark.visibility >= 0.5,
    )
  })
}

function upperBodyVisibility(landmarks: Landmark[]): number {
  const visible = UPPER_BODY_JOINTS.map((index) => landmarks[index]?.visibility ?? 0)
  return visible.reduce((total, visibility) => total + visibility, 0) / visible.length
}
