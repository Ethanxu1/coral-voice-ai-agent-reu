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

const INTERACTION_SEQUENCE_PREFIX = '__interaction_pose__:'

export function useStudioController() {
  const [projects, setProjects] = useState<Project[]>([])
  const [activeProjectId, setActiveProjectId] = useState('')
  const [humanPoses, setHumanPoses] = useState<HumanPose[]>([])
  const [robotPoses, setRobotPoses] = useState<RobotPose[]>([])
  const [allSequences, setAllSequences] = useState<MotionSequence[]>([])
  const [rules, setRules] = useState<BehaviorRule[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [outputMode, setOutputModeState] = useState<OutputMode>('simulator')
  const [triggerEnabled, setTriggerEnabledState] = useState(false)
  const [cameraEnabled, setCameraEnabledState] = useState(true)
  const [cameraBusy, setCameraBusy] = useState(false)
  const [simulatorResetting, setSimulatorResetting] = useState(false)
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
    setAllSequences(nextSequences)
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

  const resetSimulator = useCallback(async (): Promise<boolean> => {
    setSimulatorResetting(true)
    try {
      await studioApi.resetSimulator()
      setError(null)
      return true
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not reset the simulator')
      return false
    } finally {
      setSimulatorResetting(false)
    }
  }, [])

  const enterRobotPoseCapture = useCallback(
    (sessionId: string) => studioApi.enterRobotPoseCapture(sessionId).then(() => undefined),
    [],
  )

  const exitRobotPoseCapture = useCallback(
    (sessionId: string) => studioApi.exitRobotPoseCapture(sessionId).then(() => undefined),
    [],
  )

  useEffect(() => {
    let active = true
    const boot = async () => {
      try {
        await resetSimulator()
        await studioApi.setOutputMode('simulator')
        const triggerMode = await studioApi.getTriggerMode()
        let available = await studioApi.listProjects()
        if (available.length === 0) {
          available = [await studioApi.createProject('My Motion Project')]
        }
        if (!active) return
        setProjects(available)
        setActiveProjectId(available[0].id)
        setOutputModeState('simulator')
        setTriggerEnabledState(triggerMode.enabled)
      } catch (cause) {
        if (active) setError(cause instanceof Error ? cause.message : 'Studio backend unavailable')
      } finally {
        if (active) setLoading(false)
      }
    }
    void boot()
    return () => { active = false }
  }, [resetSimulator])

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

  const setTriggerEnabled = async (enabled: boolean) => {
    const result = await studioApi.setTriggerMode(enabled)
    setTriggerEnabledState(result.enabled)
  }

  const createPoseRule = async (input: {
    humanPoseId: string
    robotPoseId: string
    cooldownSeconds: number
  }) => {
    const responseSequence = await studioApi.createSequence({
      project_id: activeProjectId,
      name: `${INTERACTION_SEQUENCE_PREFIX}${input.humanPoseId}:${input.robotPoseId}:${Date.now()}`,
      steps: [{
        robot_pose_id: input.robotPoseId,
        hold_ms: 700,
        transition_ms: 300,
      }],
    })
    try {
      await studioApi.createRule({
        project_id: activeProjectId,
        human_pose_id: input.humanPoseId,
        sequence_id: responseSequence.id,
        cooldown_seconds: input.cooldownSeconds,
        priority: 0,
        enabled: true,
      })
    } catch (cause) {
      await studioApi.deleteSequence(responseSequence.id).catch(() => undefined)
      throw cause
    }
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

  const updateSequence = async (
    sequenceId: string,
    name: string,
    steps: { robotPoseId: string; holdMs: number; transitionMs: number }[],
  ) => {
    await studioApi.updateSequence(sequenceId, {
      name,
      steps: steps.map((step) => ({
        robot_pose_id: step.robotPoseId,
        hold_ms: step.holdMs,
        transition_ms: step.transitionMs,
      })),
    })
    await refresh()
  }

  const deleteInteraction = async (ruleId: string) => {
    await studioApi.deleteInteraction(ruleId)
    await refresh()
  }

  const reorderInteractions = async (ruleIds: string[]) => {
    await studioApi.reorderInteractions({ project_id: activeProjectId, rule_ids: ruleIds })
    await refresh()
  }

  const deleteHumanPose = async (poseId: string) => {
    await studioApi.deleteHumanPose(poseId)
    if (selectedId === poseId) setSelectedId(null)
    await refresh()
  }

  const deleteRobotPose = async (poseId: string) => {
    await studioApi.deleteRobotPose(poseId)
    if (selectedId === poseId) setSelectedId(null)
    await refresh()
  }

  const mirrorRobotPose = useCallback(
    (signal?: AbortSignal) => studioApi.mirrorRetargetedPose(signal),
    [],
  )

  const captureRobotPose = async (name: string, joints: Record<string, number>) => {
    if (!cameraEnabled) throw new Error('Turn on the computer camera before capturing a pose')
    if (Object.keys(joints).length === 0) throw new Error('Wait for the robot to mirror your pose')
    const pose = await studioApi.createRobotPose({
      project_id: activeProjectId,
      name,
      joints,
      thumbnail_svg: '',
      source: 'human',
    })
    const preview = await studioApi.previewRobotPose(pose.id)
    if (preview.status !== 'completed') {
      throw new Error(preview.reason ?? 'Pose was saved but could not be shown in the simulator')
    }
    await refresh()
    return pose
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

  const sequences = useMemo(
    () => allSequences.filter((sequence) => !sequence.name.startsWith(INTERACTION_SEQUENCE_PREFIX)),
    [allSequences],
  )
  const interactionRules = useMemo(
    () => rules.flatMap((rule) => {
      const sequence = allSequences.find((item) => item.id === rule.sequence_id)
      if (
        !sequence?.name.startsWith(INTERACTION_SEQUENCE_PREFIX)
        || sequence.steps.length !== 1
      ) return []
      return [{ ...rule, robot_pose_id: sequence.steps[0].robot_pose_id }]
    }),
    [allSequences, rules],
  )

  return {
    projects,
    activeProjectId,
    setActiveProjectId,
    humanPoses,
    robotPoses,
    sequences,
    rules,
    interactionRules,
    selectedId,
    setSelected: (_kind: 'human' | 'robot' | 'sequence', id: string) => setSelectedId(id),
    subjects,
    trainingApi: studioApi,
    refresh,
    resetSimulator,
    simulatorResetting,
    createPoseRule,
    deleteInteraction,
    reorderInteractions,
    createSequence,
    updateSequence,
    previewSequence: studioApi.previewSequence,
    previewRobotPose: studioApi.previewRobotPose,
    deleteHumanPose,
    deleteRobotPose,
    mirrorRobotPose,
    enterRobotPoseCapture,
    exitRobotPoseCapture,
    captureRobotPose,
    importProject,
    exportProject,
    outputMode,
    setOutputMode,
    triggerEnabled,
    setTriggerEnabled,
    cameraEnabled,
    cameraBusy,
    setCameraEnabled,
    connections: { backend: !error && !loading, vision: pose.isConnected, events: socket.connected },
    socket,
    loading,
    error,
  }
}
