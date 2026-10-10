import { useCallback, useEffect, useMemo, useState } from 'react'

import { usePoseWebSocket } from '../hooks/usePoseWebSocket'
import { studioApi } from './api'
import type {
  BehaviorRule,
  HumanPose,
  MotionSequence,
  OutputMode,
  Project,
  ProjectPackage,
  RobotPose,
} from './types'
import { useStudioSocket } from './useStudioSocket'

export function useStudioController() {
  const [projects, setProjects] = useState<Project[]>([])
  const [activeProjectId, setActiveProjectId] = useState('')
  const [humanPoses, setHumanPoses] = useState<HumanPose[]>([])
  const [robotPoses, setRobotPoses] = useState<RobotPose[]>([])
  const [sequences, setSequences] = useState<MotionSequence[]>([])
  const [rules, setRules] = useState<BehaviorRule[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [trainingOpen, setTrainingOpen] = useState(false)
  const [outputMode, setOutputModeState] = useState<OutputMode>('simulator')
  const [cameraEnabled, setCameraEnabledState] = useState(true)
  const [cameraBusy, setCameraBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const pose = usePoseWebSocket()
  const socket = useStudioSocket()

  const loadProject = useCallback(async (projectId: string) => {
    const [nextHuman, nextRobot, nextSequences, nextRules] = await Promise.all([
      studioApi.listHumanPoses(projectId),
      studioApi.listRobotPoses(projectId),
      studioApi.listSequences(projectId),
      studioApi.listRules(projectId),
    ])
    setHumanPoses(nextHuman)
    setRobotPoses(nextRobot)
    setSequences(nextSequences)
    setRules(nextRules)
  }, [])

  const refresh = useCallback(async () => {
    if (!activeProjectId) return
    try {
      await loadProject(activeProjectId)
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not refresh project')
    }
  }, [activeProjectId, loadProject])

  useEffect(() => {
    let active = true
    const boot = async () => {
      try {
        await studioApi.setOutputMode('simulator')
        let available = await studioApi.listProjects()
        if (available.length === 0) {
          available = [await studioApi.createProject('My Motion Project')]
        }
        if (!active) return
        setProjects(available)
        setActiveProjectId(available[0].id)
        setOutputModeState('simulator')
      } catch (cause) {
        if (active) setError(cause instanceof Error ? cause.message : 'Studio backend unavailable')
      } finally {
        if (active) setLoading(false)
      }
    }
    void boot()
    return () => { active = false }
  }, [])

  useEffect(() => {
    let active = true
    void studioApi.getCameraState()
      .then((state) => {
        if (active) setCameraEnabledState(state.enabled)
      })
      .catch(() => {
        if (active) setCameraEnabledState(false)
      })
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!activeProjectId) return
    void loadProject(activeProjectId).catch((cause) =>
      setError(cause instanceof Error ? cause.message : 'Could not load project'),
    )
  }, [activeProjectId, loadProject])

  useEffect(() => {
    if (socket.connected) return
    setOutputModeState('simulator')
    void studioApi.setOutputMode('simulator').catch(() => undefined)
  }, [socket.connected])

  useEffect(() => {
    if (socket.latestEvent?.type === 'hardware_unavailable') setOutputModeState('simulator')
  }, [socket.latestEvent])

  const subjects = useMemo(
    () => cameraEnabled
      ? pose.subjects.map((subject) => ({ id: subject.id, landmarks: subject.body_landmarks }))
      : [],
    [cameraEnabled, pose.subjects],
  )

  const setCameraEnabled = async (enabled: boolean) => {
    setCameraBusy(true)
    try {
      const state = await studioApi.setCameraEnabled(enabled)
      setCameraEnabledState(state.enabled)
      setError(null)
    } catch (cause) {
      if (enabled) setCameraEnabledState(false)
      setError(cause instanceof Error ? cause.message : 'Camera unavailable')
    } finally {
      setCameraBusy(false)
    }
  }

  const setOutputMode = async (mode: OutputMode) => {
    const result = await studioApi.setOutputMode(mode)
    setOutputModeState(result.mode)
  }

  const createRule = async (input: {
    humanPoseId: string
    sequenceId: string
    cooldownSeconds: number
  }) => {
    await studioApi.createRule({
      project_id: activeProjectId,
      human_pose_id: input.humanPoseId,
      sequence_id: input.sequenceId,
      cooldown_seconds: input.cooldownSeconds,
      priority: 0,
      enabled: true,
    })
    await refresh()
  }

  const createSequence = async (
    name: string,
    steps: { robotPoseId: string; holdMs: number; transitionMs: number }[],
  ) => {
    await studioApi.createSequence({
      project_id: activeProjectId,
      name,
      steps: steps.map((step) => ({
        robot_pose_id: step.robotPoseId,
        hold_ms: step.holdMs,
        transition_ms: step.transitionMs,
      })),
    })
    await refresh()
  }

  const captureRobotPose = async (name: string) => {
    if (!cameraEnabled) throw new Error('Turn on the computer camera before capturing a pose')
    const captured = await studioApi.captureRetargetedPose()
    await studioApi.createRobotPose({
      project_id: activeProjectId,
      name,
      joints: captured.targets,
      thumbnail_svg: '',
      source: 'human',
    })
    await refresh()
  }

  const importProject = async (file: File) => {
    const payload = JSON.parse(await file.text()) as ProjectPackage
    await studioApi.setOutputMode('simulator')
    const result = await studioApi.importProject(payload)
    const available = await studioApi.listProjects()
    setProjects(available)
    setActiveProjectId(result.project_id)
    setOutputModeState('simulator')
  }

  const exportProject = async () => {
    const payload = await studioApi.exportProject(activeProjectId)
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${payload.project.name ?? 'motion-project'}.json`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  return {
    projects,
    activeProjectId,
    setActiveProjectId,
    humanPoses,
    robotPoses,
    sequences,
    rules,
    selectedId,
    setSelected: (_kind: 'human' | 'robot' | 'sequence', id: string) => setSelectedId(id),
    trainingOpen,
    setTrainingOpen,
    subjects,
    trainingApi: studioApi,
    refresh,
    createRule,
    createSequence,
    previewSequence: studioApi.previewSequence,
    captureRobotPose,
    importProject,
    exportProject,
    outputMode,
    setOutputMode,
    cameraEnabled,
    cameraBusy,
    setCameraEnabled,
    connections: { backend: !error && !loading, vision: pose.isConnected, events: socket.connected },
    socket,
    loading,
    error,
  }
}
