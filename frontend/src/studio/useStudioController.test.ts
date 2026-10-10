import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useStudioController } from './useStudioController'

const mocks = vi.hoisted(() => ({
  captureRetargetedPose: vi.fn(),
  createRobotPose: vi.fn(),
  previewRobotPose: vi.fn(),
  listProjects: vi.fn(),
  listHumanPoses: vi.fn(),
  listRobotPoses: vi.fn(),
  listSequences: vi.fn(),
  listRules: vi.fn(),
  setOutputMode: vi.fn(),
  getCameraState: vi.fn(),
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
    mocks.getCameraState.mockResolvedValue({ enabled: true })
    mocks.captureRetargetedPose.mockResolvedValue({
      targets: { l_sho_pitch: 0.4 },
      body_landmarks: [],
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
  })

  it('shows a captured pose in the simulator after saving it', async () => {
    const { result } = renderHook(() => useStudioController())
    await waitFor(() => expect(result.current.activeProjectId).toBe('project-1'))

    await act(async () => {
      await result.current.captureRobotPose('Reach high')
    })

    expect(mocks.previewRobotPose).toHaveBeenCalledWith('pose-1')
  })
})
