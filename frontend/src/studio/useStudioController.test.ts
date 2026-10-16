import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useStudioController } from './useStudioController'

const mocks = vi.hoisted(() => ({
  mirrorRetargetedPose: vi.fn(),
  createRobotPose: vi.fn(),
  previewRobotPose: vi.fn(),
  listProjects: vi.fn(),
  listHumanPoses: vi.fn(),
  listRobotPoses: vi.fn(),
  listSequences: vi.fn(),
  listRules: vi.fn(),
  setOutputMode: vi.fn(),
  getTriggerMode: vi.fn(),
  setTriggerMode: vi.fn(),
  getCameraState: vi.fn(),
  resetSimulator: vi.fn(),
  deleteHumanPose: vi.fn(),
  deleteRobotPose: vi.fn(),
  createSequence: vi.fn(),
  updateSequence: vi.fn(),
  deleteSequence: vi.fn(),
  deleteInteraction: vi.fn(),
  reorderInteractions: vi.fn(),
  createRule: vi.fn(),
}))

vi.mock('./api', () => ({
  studioApi: {
    ...mocks,
    createProject: vi.fn(),
  },
}))
vi.mock('../hooks/usePoseWebSocket', () => ({
  usePoseWebSocket: () => ({ subjects: [], isConnected: true }),
}))
vi.mock('./useStudioSocket', () => ({
  useStudioSocket: () => ({
    connected: true,
    latestEvent: null,
    recognition: {},
    holds: {},
    executingSequenceId: null,
    statusMessage: null,
  }),
}))

describe('useStudioController', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.listProjects.mockResolvedValue([{ id: 'project-1', name: 'Classroom' }])
    mocks.listHumanPoses.mockResolvedValue([])
    mocks.listRobotPoses.mockResolvedValue([])
    mocks.listSequences.mockResolvedValue([])
    mocks.listRules.mockResolvedValue([])
    mocks.setOutputMode.mockResolvedValue({ mode: 'simulator' })
    mocks.getTriggerMode.mockResolvedValue({ enabled: false })
    mocks.setTriggerMode.mockResolvedValue({ enabled: true })
    mocks.getCameraState.mockResolvedValue({ enabled: true })
    mocks.resetSimulator.mockResolvedValue(undefined)
    mocks.deleteHumanPose.mockResolvedValue({ deleted: true })
    mocks.deleteRobotPose.mockResolvedValue({ deleted: true })
    mocks.mirrorRetargetedPose.mockResolvedValue({
      status: 'done',
      targets: { l_sho_pitch: 0.4 },
      safety: {
        fall_blocked: false,
        collision_clamped: false,
        safe_fraction: 1,
        bad_pairs: [],
      },
    })
    mocks.createRobotPose.mockResolvedValue({
      id: 'pose-1',
      project_id: 'project-1',
      name: 'Reach high',
      joints: { l_sho_pitch: 0.4 },
      thumbnail_svg: '',
      source: 'human',
      safety: { safe: true },
    })
    mocks.previewRobotPose.mockResolvedValue({ status: 'completed' })
    mocks.createSequence.mockResolvedValue({
      id: 'interaction-sequence-1',
      name: '__interaction_pose__:human-1:robot-1',
      steps: [{ robot_pose_id: 'robot-1', hold_ms: 700, transition_ms: 300 }],
    })
    mocks.updateSequence.mockResolvedValue({ id: 'sequence-1' })
    mocks.createRule.mockResolvedValue({ id: 'rule-1' })
    mocks.deleteSequence.mockResolvedValue({ deleted: true })
    mocks.deleteInteraction.mockResolvedValue({ deleted: true })
    mocks.reorderInteractions.mockResolvedValue({ reordered: true })
  })

  it('saves the latest safety-adjusted pose shown by live mirroring', async () => {
    const { result } = renderHook(() => useStudioController())
    await waitFor(() => expect(result.current.activeProjectId).toBe('project-1'))

    await act(async () => {
      await result.current.captureRobotPose('Reach high', { l_sho_pitch: 0.25 })
    })

    expect(mocks.createRobotPose).toHaveBeenCalledWith(expect.objectContaining({
      joints: { l_sho_pitch: 0.25 },
    }))
    expect(mocks.previewRobotPose).toHaveBeenCalledWith('pose-1')
  })

  it('resets only the simulator when Motion Studio mounts', async () => {
    renderHook(() => useStudioController())

    await waitFor(() => expect(mocks.resetSimulator).toHaveBeenCalledTimes(1))
  })

  it('exposes a manual simulator reset action', async () => {
    const { result } = renderHook(() => useStudioController())
    await waitFor(() => expect(result.current.activeProjectId).toBe('project-1'))
    mocks.resetSimulator.mockClear()

    await act(async () => {
      await result.current.resetSimulator()
    })

    expect(mocks.resetSimulator).toHaveBeenCalledOnce()
  })

  it('deletes saved poses and refreshes the project lists', async () => {
    const { result } = renderHook(() => useStudioController())
    await waitFor(() => expect(result.current.activeProjectId).toBe('project-1'))
    mocks.listHumanPoses.mockClear()
    mocks.listRobotPoses.mockClear()

    await act(async () => {
      await result.current.deleteHumanPose('human-1')
      await result.current.deleteRobotPose('robot-1')
    })

    expect(mocks.deleteHumanPose).toHaveBeenCalledWith('human-1')
    expect(mocks.deleteRobotPose).toHaveBeenCalledWith('robot-1')
    expect(mocks.listHumanPoses).toHaveBeenCalledTimes(2)
    expect(mocks.listRobotPoses).toHaveBeenCalledTimes(2)
  })

  it('starts trigger recognition only when requested', async () => {
    const { result } = renderHook(() => useStudioController())
    await waitFor(() => expect(result.current.activeProjectId).toBe('project-1'))

    await act(async () => {
      await result.current.setTriggerEnabled(true)
    })

    expect(mocks.setTriggerMode).toHaveBeenCalledWith(true)
    expect(result.current.triggerEnabled).toBe(true)
  })

  it('creates a direct pose interaction without exposing its internal response sequence', async () => {
    mocks.listSequences.mockResolvedValueOnce([]).mockResolvedValue([
      {
        id: 'interaction-sequence-1',
        name: '__interaction_pose__:human-1:robot-1',
        steps: [{ robot_pose_id: 'robot-1', hold_ms: 700, transition_ms: 300 }],
      },
      { id: 'public-sequence', name: 'Dance', steps: [] },
    ])
    const { result } = renderHook(() => useStudioController())
    await waitFor(() => expect(result.current.activeProjectId).toBe('project-1'))

    await act(async () => {
      await result.current.createPoseRule({
        humanPoseId: 'human-1',
        robotPoseId: 'robot-1',
        cooldownSeconds: 2,
      })
    })

    expect(mocks.createSequence).toHaveBeenCalledWith(expect.objectContaining({
      steps: [{ robot_pose_id: 'robot-1', hold_ms: 700, transition_ms: 300 }],
    }))
    expect(mocks.createRule).toHaveBeenCalledWith(expect.objectContaining({
      human_pose_id: 'human-1',
      sequence_id: 'interaction-sequence-1',
      cooldown_seconds: 2,
    }))
    expect(result.current.sequences.map((sequence) => sequence.name)).toEqual(['Dance'])
  })

  it('does not present legacy multi-step rules as direct pose interactions', async () => {
    mocks.listSequences.mockResolvedValue([
      {
        id: 'legacy-sequence',
        name: 'Dance',
        steps: [
          { robot_pose_id: 'robot-1', hold_ms: 700, transition_ms: 300 },
          { robot_pose_id: 'robot-2', hold_ms: 700, transition_ms: 300 },
        ],
      },
    ])
    mocks.listRules.mockResolvedValue([
      { id: 'legacy-rule', human_pose_id: 'human-1', sequence_id: 'legacy-sequence' },
    ])

    const { result } = renderHook(() => useStudioController())
    await waitFor(() => expect(result.current.sequences).toHaveLength(1))

    expect(result.current.interactionRules).toEqual([])
  })

  it('updates an existing sequence and refreshes its saved value', async () => {
    const { result } = renderHook(() => useStudioController())
    await waitFor(() => expect(result.current.activeProjectId).toBe('project-1'))
    mocks.listSequences.mockClear()

    await act(async () => {
      await result.current.updateSequence('sequence-1', 'Welcome', [
        { robotPoseId: 'robot-1', holdMs: 900, transitionMs: 400 },
      ])
    })

    expect(mocks.updateSequence).toHaveBeenCalledWith('sequence-1', {
      name: 'Welcome',
      steps: [{ robot_pose_id: 'robot-1', hold_ms: 900, transition_ms: 400 }],
    })
    expect(mocks.listSequences).toHaveBeenCalledOnce()
  })

  it('removes the hidden response sequence when interaction rule creation fails', async () => {
    mocks.createRule.mockRejectedValueOnce(new Error('Rule save failed'))
    const { result } = renderHook(() => useStudioController())
    await waitFor(() => expect(result.current.activeProjectId).toBe('project-1'))

    await expect(result.current.createPoseRule({
      humanPoseId: 'human-1',
      robotPoseId: 'robot-1',
      cooldownSeconds: 2,
    })).rejects.toThrow('Rule save failed')

    expect(mocks.deleteSequence).toHaveBeenCalledWith('interaction-sequence-1')
  })

  it('deletes and reorders interactions through persistent API operations', async () => {
    const { result } = renderHook(() => useStudioController())
    await waitFor(() => expect(result.current.activeProjectId).toBe('project-1'))

    await act(async () => {
      await result.current.deleteInteraction('rule-1')
      await result.current.reorderInteractions(['rule-2', 'rule-1'])
    })

    expect(mocks.deleteInteraction).toHaveBeenCalledWith('rule-1')
    expect(mocks.reorderInteractions).toHaveBeenCalledWith({
      project_id: 'project-1',
      rule_ids: ['rule-2', 'rule-1'],
    })
  })
})
