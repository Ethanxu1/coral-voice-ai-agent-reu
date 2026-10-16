import { useEffect, useMemo, useRef, useState } from 'react'
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
  const [editingSequenceId, setEditingSequenceId] = useState<string | null>(null)
  const [robotPoseId, setRobotPoseId] = useState('')
  const [trainingOpen, setTrainingOpen] = useState(false)
  const [captureOpen, setCaptureOpen] = useState(false)
  const [captureName, setCaptureName] = useState('')
  const [actionMessage, setActionMessage] = useState<string | null>(null)
  const [sequencePlaying, setSequencePlaying] = useState(false)
  const [triggerBusy, setTriggerBusy] = useState(false)
  const [interactionBusy, setInteractionBusy] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const selectedSequence = useMemo(
    () => studio.sequences.find((sequence) => sequence.id === studio.selectedId),
    [studio.sequences, studio.selectedId],
  )
  const humanPoseNamesById = useMemo(
    () => Object.fromEntries(studio.humanPoses.map((pose) => [pose.id, pose.name])),
    [studio.humanPoses],
  )

  useEffect(() => {
    setEditingSequenceId(null)
    setSequenceName('')
    setDraftSteps([])
  }, [studio.activeProjectId])

  const clearSequenceDraft = () => {
    setEditingSequenceId(null)
    setSequenceName('')
    setDraftSteps([])
    setRobotPoseId('')
  }

  const editSequence = (sequenceId: string) => {
    const sequence = studio.sequences.find((item) => item.id === sequenceId)
    if (!sequence) return
    setEditingSequenceId(sequence.id)
    setSequenceName(sequence.name)
    setDraftSteps(sequence.steps.map((step, index) => ({
      id: step.id ?? `${sequence.id}-step-${index}`,
      robotPoseId: step.robot_pose_id,
      poseName: studio.robotPoses.find((pose) => pose.id === step.robot_pose_id)?.name ?? 'Unknown pose',
      holdMs: step.hold_ms,
      transitionMs: step.transition_ms,
    })))
    document.getElementById('sequence-name')?.focus()
  }

  const selectLibraryBlock = (kind: 'human' | 'robot' | 'sequence', id: string) => {
    studio.setSelected(kind, id)
    if (kind === 'sequence') editSequence(id)
  }

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
      if (editingSequenceId) {
        await studio.updateSequence(editingSequenceId, sequenceName.trim(), draftSteps)
        setActionMessage('Sequence updated')
      } else {
        await studio.createSequence(sequenceName.trim(), draftSteps)
        clearSequenceDraft()
        setActionMessage('Sequence saved')
      }
    } catch (error) {
      setActionMessage(error instanceof Error ? error.message : 'Could not save sequence')
    }
  }

  const saveRobotPose = async (name: string, joints: Record<string, number>) => {
    if (!name.trim()) return
    const pose = await studio.captureRobotPose(name.trim(), joints)
    setActionMessage('Robot pose passed safety checks, was saved, and is shown in the simulator')
    return pose
  }

  const previewSavedSequence = async (sequenceId: string) => {
    if (sequencePlaying) return
    setSequencePlaying(true)
    setActionMessage('Playing sequence in simulator…')
    try {
      if (studio.outputMode !== 'simulator') {
        await studio.setOutputMode('simulator')
      }
      const result = await studio.previewSequence(sequenceId)
      if (result.status !== 'completed') {
        throw new Error(result.reason ?? 'Sequence preview was blocked')
      }
      setActionMessage(
        result.reason === 'collision_risk'
          ? 'Sequence preview complete with simulator-only collision warning'
          : result.reason === 'fall_risk'
            ? 'Sequence preview complete with simulator stabilization'
            : 'Sequence preview complete',
      )
    } catch (error) {
      setActionMessage(error instanceof Error ? error.message : 'Could not preview sequence')
    } finally {
      setSequencePlaying(false)
    }
  }

  const previewSavedRobotPose = async (poseId: string) => {
    if (sequencePlaying) return
    setSequencePlaying(true)
    try {
      if (studio.outputMode !== 'simulator') {
        await studio.setOutputMode('simulator')
      }
      const result = await studio.previewRobotPose(poseId)
      if (result.status !== 'completed') {
        throw new Error(result.reason ?? 'Robot pose preview was blocked')
      }
      setActionMessage('Robot pose shown in simulator')
    } catch (error) {
      setActionMessage(error instanceof Error ? error.message : 'Could not preview robot pose')
    } finally {
      setSequencePlaying(false)
    }
  }

  const toggleTriggerMode = async () => {
    if (triggerBusy) return
    setTriggerBusy(true)
    const enabled = !studio.triggerEnabled
    try {
      await studio.setTriggerEnabled(enabled)
      setActionMessage(
        enabled
          ? 'Trigger Mode started — perform a trained pose'
          : 'Trigger Mode stopped',
      )
    } catch (error) {
      setActionMessage(error instanceof Error ? error.message : 'Could not change Trigger Mode')
    } finally {
      setTriggerBusy(false)
    }
  }

  const deleteHumanPose = async (poseId: string) => {
    try {
      await studio.deleteHumanPose(poseId)
      setActionMessage('Human pose deleted')
    } catch (error) {
      setActionMessage(error instanceof Error ? error.message : 'Could not delete human pose')
    }
  }

  const deleteRobotPose = async (poseId: string) => {
    try {
      await studio.deleteRobotPose(poseId)
      setActionMessage('Robot pose deleted')
    } catch (error) {
      setActionMessage(error instanceof Error ? error.message : 'Could not delete robot pose')
    }
  }

  const saveInteraction = async (rule: {
    humanPoseId: string
    robotPoseId: string
    cooldownSeconds: number
  }) => {
    if (interactionBusy) return
    setInteractionBusy(true)
    try {
      await studio.createPoseRule(rule)
      setActionMessage('Interaction saved')
    } catch (error) {
      setActionMessage(error instanceof Error ? error.message : 'Could not save interaction')
    } finally {
      setInteractionBusy(false)
    }
  }

  const deleteInteraction = async (ruleId: string) => {
    if (interactionBusy) return
    setInteractionBusy(true)
    try {
      await studio.deleteInteraction(ruleId)
      setActionMessage('Interaction deleted')
    } catch (error) {
      setActionMessage(error instanceof Error ? error.message : 'Could not delete interaction')
    } finally {
      setInteractionBusy(false)
    }
  }

  const reorderInteractions = async (ruleIds: string[]) => {
    if (interactionBusy) return
    setInteractionBusy(true)
    try {
      await studio.reorderInteractions(ruleIds)
      setActionMessage('Interaction order saved')
    } catch (error) {
      setActionMessage(error instanceof Error ? error.message : 'Could not reorder interactions')
    } finally {
      setInteractionBusy(false)
    }
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
          onSelect={selectLibraryBlock}
          onTrainHumanPose={() => setTrainingOpen(true)}
          onCaptureRobotPose={() => setCaptureOpen(true)}
          onCreateSequence={() => {
            clearSequenceDraft()
            document.getElementById('sequence-name')?.focus()
          }}
          onDeleteHumanPose={(poseId) => void deleteHumanPose(poseId)}
          onDeleteRobotPose={(poseId) => void deleteRobotPose(poseId)}
          onPreviewRobotPose={(poseId) => void previewSavedRobotPose(poseId)}
          onPreviewSequence={(sequenceId) => void previewSavedSequence(sequenceId)}
          previewBusy={sequencePlaying}
        />

        <div className="studio-compose-column">
          <RuleCanvas
            humanPoses={studio.humanPoses}
            robotPoses={studio.robotPoses}
            rules={studio.interactionRules}
            onCreateRule={saveInteraction}
            onPreviewRobotPose={(poseId) => void previewSavedRobotPose(poseId)}
            onDeleteRule={deleteInteraction}
            onReorderRules={reorderInteractions}
            previewBusy={sequencePlaying}
            createBusy={interactionBusy}
          />
          <section className="sequence-composer" aria-labelledby="sequence-composer-title">
            <header className="studio-panel-heading">
              <div>
                <span className="studio-kicker">Robot choreography</span>
                <h2 id="sequence-composer-title">Sequence Composer</h2>
              </div>
              <div className="sequence-mode-actions">
                <button
                  type="button"
                  className="studio-secondary-button"
                  disabled={triggerBusy}
                  onClick={() => void toggleTriggerMode()}
                >
                  {studio.triggerEnabled ? 'Stop Trigger Mode' : 'Start Trigger Mode'}
                </button>
                {selectedSequence && (
                  <button
                    type="button"
                    className="studio-secondary-button"
                    disabled={sequencePlaying}
                    onClick={() => void previewSavedSequence(selectedSequence.id)}
                  >
                    {sequencePlaying ? 'Playing…' : `Play ${selectedSequence.name}`}
                  </button>
                )}
              </div>
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
              <div className="sequence-save-actions">
                {editingSequenceId && (
                  <button
                    type="button"
                    className="studio-secondary-button"
                    onClick={clearSequenceDraft}
                  >
                    Cancel edit
                  </button>
                )}
                <button
                  type="button"
                  className="studio-primary-button"
                  disabled={!sequenceName.trim() || draftSteps.length === 0}
                  onClick={() => void saveSequence()}
                >
                  {editingSequenceId ? 'Update sequence' : 'Save sequence'}
                </button>
              </div>
            </footer>
          </section>
        </div>

        {!captureOpen && (
          <LivePreview
            subjects={studio.subjects}
            recognition={studio.socket.recognition}
            poseNamesById={humanPoseNamesById}
            holds={studio.socket.holds}
            executingSequenceId={studio.socket.executingSequenceId}
            statusMessage={studio.socket.statusMessage}
            cameraEnabled={studio.cameraEnabled}
            onResetSimulator={studio.resetSimulator}
            simulatorResetting={studio.simulatorResetting}
          />
        )}
      </div>

      {trainingOpen && (
        <PoseTrainingDialog
          open
          projectId={studio.activeProjectId}
          existingNames={studio.humanPoses.map((pose) => pose.name)}
          subjects={studio.subjects}
          api={studio.trainingApi}
          onSaved={() => {
            setTrainingOpen(false)
            void studio.refresh()
          }}
          onClose={() => setTrainingOpen(false)}
        />
      )}

      {captureOpen && (
        <RobotPoseCaptureWorkspace
          open
          name={captureName}
          cameraEnabled={studio.cameraEnabled}
          onNameChange={setCaptureName}
          onMirror={studio.mirrorRobotPose}
          onCapture={saveRobotPose}
          onEnterCapture={studio.enterRobotPoseCapture}
          onExitCapture={studio.exitRobotPoseCapture}
          onResetSimulator={studio.resetSimulator}
          simulatorResetting={studio.simulatorResetting}
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
