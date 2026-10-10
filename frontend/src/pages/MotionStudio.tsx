import { useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import { BlockLibrary } from '../studio/BlockLibrary'
import { LivePreview } from '../studio/LivePreview'
import { PoseTrainingDialog } from '../studio/PoseTrainingDialog'
import { RobotPoseCaptureWorkspace } from '../studio/RobotPoseCaptureWorkspace'
import { RuleCanvas } from '../studio/RuleCanvas'
import { SequenceEditor, type EditableSequenceStep } from '../studio/SequenceEditor'
import { useStudioController } from '../studio/useStudioController'
import './MotionStudio.css'

export default function MotionStudio() {
  const studio = useStudioController()
  const [sequenceName, setSequenceName] = useState('')
  const [draftSteps, setDraftSteps] = useState<EditableSequenceStep[]>([])
  const [robotPoseId, setRobotPoseId] = useState('')
  const [captureOpen, setCaptureOpen] = useState(false)
  const [captureName, setCaptureName] = useState('')
  const [actionMessage, setActionMessage] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const selectedSequence = useMemo(
    () => studio.sequences.find((sequence) => sequence.id === studio.selectedId),
    [studio.sequences, studio.selectedId],
  )

  const addRobotPose = () => {
    const pose = studio.robotPoses.find((item) => item.id === robotPoseId)
    if (!pose) return
    setDraftSteps((current) => [
      ...current,
      {
        id: `${pose.id}-${Date.now()}-${current.length}`,
        robotPoseId: pose.id,
        poseName: pose.name,
        holdMs: 700,
        transitionMs: 300,
      },
    ])
  }

  const saveSequence = async () => {
    if (!sequenceName.trim() || draftSteps.length === 0) return
    try {
      await studio.createSequence(sequenceName.trim(), draftSteps)
      setSequenceName('')
      setDraftSteps([])
      setActionMessage('Sequence saved')
    } catch (error) {
      setActionMessage(error instanceof Error ? error.message : 'Could not save sequence')
    }
  }

  const saveRobotPose = async () => {
    if (!captureName.trim()) return
    const pose = await studio.captureRobotPose(captureName.trim())
    setActionMessage('Robot pose passed safety checks, was saved, and is shown in the simulator')
    return pose
  }

  return (
    <main className="motion-studio">
      <StudioHeader
        projects={studio.projects}
        activeProjectId={studio.activeProjectId}
        onProjectChange={studio.setActiveProjectId}
        connections={studio.connections}
        outputMode={studio.outputMode}
        onOutputModeChange={studio.setOutputMode}
        cameraEnabled={studio.cameraEnabled}
        cameraBusy={studio.cameraBusy}
        onCameraChange={studio.setCameraEnabled}
        onExport={() => void studio.exportProject()}
        onImport={() => fileInput.current?.click()}
      />
      <input
        ref={fileInput}
        type="file"
        accept="application/json"
        hidden
        aria-label="Import project package"
        onChange={(event) => {
          const file = event.target.files?.[0]
          if (file) void studio.importProject(file)
          event.target.value = ''
        }}
      />

      {(studio.error || actionMessage) && (
        <div className={`studio-banner${studio.error ? ' is-error' : ''}`} role="status">
          {studio.error ?? actionMessage}
          <button type="button" onClick={() => setActionMessage(null)} aria-label="Dismiss message">×</button>
        </div>
      )}

      <div className="motion-studio__columns">
        <BlockLibrary
          humanPoses={studio.humanPoses}
          robotPoses={studio.robotPoses}
          sequences={studio.sequences}
          selectedId={studio.selectedId}
          onSelect={studio.setSelected}
          onTrainHumanPose={() => studio.setTrainingOpen(true)}
          onCaptureRobotPose={() => setCaptureOpen(true)}
          onCreateSequence={() => document.getElementById('sequence-name')?.focus()}
        />

        <div className="studio-compose-column">
          <RuleCanvas
            humanPoses={studio.humanPoses}
            sequences={studio.sequences}
            rules={studio.rules}
            onCreateRule={(rule) => void studio.createRule(rule)}
          />
          <section className="sequence-composer" aria-labelledby="sequence-composer-title">
            <header className="studio-panel-heading">
              <div>
                <span className="studio-kicker">Robot choreography</span>
                <h2 id="sequence-composer-title">Sequence Composer</h2>
              </div>
              {selectedSequence && (
                <button
                  type="button"
                  className="studio-secondary-button"
                  onClick={() => void studio.previewSequence(selectedSequence.id)}
                >
                  Preview {selectedSequence.name}
                </button>
              )}
            </header>
            <div className="sequence-name-row">
              <label>
                Sequence name
                <input
                  id="sequence-name"
                  value={sequenceName}
                  onChange={(event) => setSequenceName(event.target.value)}
                  placeholder="Celebrate"
                />
              </label>
              <label>
                Robot pose
                <select value={robotPoseId} onChange={(event) => setRobotPoseId(event.target.value)}>
                  <option value="">Choose a pose</option>
                  {studio.robotPoses.map((pose) => <option key={pose.id} value={pose.id}>{pose.name}</option>)}
                </select>
              </label>
              <button type="button" className="studio-secondary-button" disabled={!robotPoseId} onClick={addRobotPose}>
                Add step
              </button>
            </div>
            <SequenceEditor
              steps={draftSteps}
              onChange={setDraftSteps}
              onRemove={(id) => setDraftSteps((current) => current.filter((step) => step.id !== id))}
            />
            <footer className="sequence-composer-footer">
              <span>{draftSteps.length} {draftSteps.length === 1 ? 'step' : 'steps'}</span>
              <button
                type="button"
                className="studio-primary-button"
                disabled={!sequenceName.trim() || draftSteps.length === 0}
                onClick={() => void saveSequence()}
              >
                Save sequence
              </button>
            </footer>
          </section>
        </div>

        {!captureOpen && (
          <LivePreview
            subjects={studio.subjects}
            recognition={studio.socket.recognition}
            holds={studio.socket.holds}
            executingSequenceId={studio.socket.executingSequenceId}
            statusMessage={studio.socket.statusMessage}
            cameraEnabled={studio.cameraEnabled}
          />
        )}
      </div>

      <PoseTrainingDialog
        open={studio.trainingOpen}
        projectId={studio.activeProjectId}
        existingNames={studio.humanPoses.map((pose) => pose.name)}
        subjects={studio.subjects}
        api={studio.trainingApi}
        onSaved={() => {
          studio.setTrainingOpen(false)
          void studio.refresh()
        }}
        onClose={() => studio.setTrainingOpen(false)}
      />

      {captureOpen && (
        <RobotPoseCaptureWorkspace
          open
          name={captureName}
          cameraEnabled={studio.cameraEnabled}
          onNameChange={setCaptureName}
          onCapture={saveRobotPose}
          onClose={() => {
            setCaptureOpen(false)
            setCaptureName('')
          }}
        />
      )}
    </main>
  )
}

function StudioHeader({
  projects,
  activeProjectId,
  onProjectChange,
  connections,
  outputMode,
  onOutputModeChange,
  cameraEnabled,
  cameraBusy,
  onCameraChange,
  onExport,
  onImport,
}: {
  projects: { id: string; name: string }[]
  activeProjectId: string
  onProjectChange: (id: string) => void
  connections: { backend: boolean; vision: boolean; events: boolean }
  outputMode: 'simulator' | 'live_robot'
  onOutputModeChange: (mode: 'simulator' | 'live_robot') => void | Promise<void>
  cameraEnabled: boolean
  cameraBusy: boolean
  onCameraChange: (enabled: boolean) => void | Promise<void>
  onExport: () => void
  onImport: () => void
}) {
  return (
    <header className="motion-studio__header">
      <div className="studio-brand">
        <Link to="/" aria-label="Back to launcher">coral<span>°</span></Link>
        <div><strong>Motion Block Studio</strong><small>Teach a gesture. Compose a response.</small></div>
      </div>
      <label className="project-picker">
        Project
        <select value={activeProjectId} onChange={(event) => onProjectChange(event.target.value)}>
          {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
        </select>
      </label>
      <div className="studio-connections" aria-label="Connection status">
        <ConnectionPill label="Backend" active={connections.backend} />
        <ConnectionPill label="Vision" active={connections.vision} />
        <ConnectionPill label="Events" active={connections.events} />
      </div>
      <div className="studio-file-actions">
        <button type="button" onClick={onImport}>Import</button>
        <button type="button" onClick={onExport}>Export</button>
      </div>
      <label className="camera-gate">
        <input
          type="checkbox"
          role="switch"
          aria-label="Computer Camera"
          checked={cameraEnabled}
          disabled={cameraBusy}
          onChange={(event) => void onCameraChange(event.target.checked)}
        />
        <i aria-hidden="true" />
        Camera {cameraBusy ? '…' : cameraEnabled ? 'On' : 'Off'}
      </label>
      <div className="output-gate">
        <span className={outputMode === 'simulator' ? 'is-active' : ''}>Simulator</span>
        <label>
          <input
            type="checkbox"
            role="switch"
            aria-label="Live Robot"
            checked={outputMode === 'live_robot'}
            onChange={(event) => void onOutputModeChange(event.target.checked ? 'live_robot' : 'simulator')}
          />
          <i aria-hidden="true" />
          Live Robot
        </label>
      </div>
    </header>
  )
}

function ConnectionPill({ label, active }: { label: string; active: boolean }) {
  return <span className={active ? 'is-online' : ''}><i aria-hidden="true" />{label}</span>
}
