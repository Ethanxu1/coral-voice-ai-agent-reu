import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { Landmark } from '../studio/types'
import MotionStudio from './MotionStudio'

const controller = {
  projects: [{ id: 'p1', name: 'Classroom' }],
  activeProjectId: 'p1',
  setActiveProjectId: vi.fn(),
  humanPoses: [{ id: 'h1', name: 'Hands up' }],
  robotPoses: [{ id: 'r1', name: 'Wave' }],
  sequences: [{
    id: 's1',
    name: 'Celebrate',
    steps: [{ id: 'step-1', robot_pose_id: 'r1', hold_ms: 700, transition_ms: 300 }],
  }],
  rules: [],
  selectedId: null as string | null,
  setSelected: vi.fn(),
  subjects: [] as { id: string; landmarks: Landmark[] }[],
  trainingApi: { createHumanPose: vi.fn(), addHumanPoseSample: vi.fn() },
  refresh: vi.fn(),
  createRule: vi.fn(),
  createPoseRule: vi.fn(),
  deleteInteraction: vi.fn(),
  reorderInteractions: vi.fn(),
  interactionRules: [],
  createSequence: vi.fn(),
  updateSequence: vi.fn(),
  previewSequence: vi.fn(),
  previewRobotPose: vi.fn(),
  triggerEnabled: false,
  setTriggerEnabled: vi.fn(),
  deleteHumanPose: vi.fn(),
  deleteRobotPose: vi.fn(),
  mirrorRobotPose: vi.fn(),
  enterRobotPoseCapture: vi.fn(),
  exitRobotPoseCapture: vi.fn(),
  captureRobotPose: vi.fn(),
  importProject: vi.fn(),
  exportProject: vi.fn(),
  resetSimulator: vi.fn(),
  simulatorResetting: false,
  outputMode: 'simulator' as const,
  setOutputMode: vi.fn(),
  cameraEnabled: true,
  cameraBusy: false,
  setCameraEnabled: vi.fn(),
  connections: { backend: true, vision: true, events: true },
  socket: {
    connected: true,
    recognition: {},
    holds: {},
    executingSequenceId: null,
    statusMessage: null,
  },
  loading: false,
  error: null,
}

vi.mock('../studio/useStudioController', () => ({
  useStudioController: () => controller,
}))
vi.mock('../components/RobotViewer', () => ({
  default: ({ onStabilityChange }: { onStabilityChange?: (fallen: boolean) => void }) => (
    <div>
      Simulator viewport
      <button type="button" onClick={() => onStabilityChange?.(true)}>Simulate fall</button>
    </div>
  ),
}))

describe('MotionStudio', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    controller.selectedId = null
    controller.triggerEnabled = false
    controller.subjects = []
    controller.socket.recognition = {}
    controller.socket.holds = {}
    controller.mirrorRobotPose.mockResolvedValue({
      status: 'done',
      targets: { l_sho_pitch: 0.25, l_knee: 0.1 },
      safety: {
        fall_blocked: false,
        collision_clamped: false,
        safe_fraction: 1,
        bad_pairs: [],
      },
    })
    controller.enterRobotPoseCapture.mockResolvedValue(undefined)
    controller.exitRobotPoseCapture.mockResolvedValue(undefined)
    controller.resetSimulator.mockResolvedValue(true)
    controller.updateSequence.mockResolvedValue(undefined)
  })

  const renderStudio = () => render(
    <MemoryRouter>
      <MotionStudio />
    </MemoryRouter>,
  )

  it('defaults to simulator and renders the three columns', () => {
    renderStudio()

    expect(screen.getByRole('heading', { name: 'Block Library' })).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Interaction Sequencer' })).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Live Preview' })).toBeVisible()
    expect(screen.getByText('Simulator')).toBeVisible()
    expect(screen.getByRole('switch', { name: 'Live Robot' })).not.toBeChecked()
  })

  it('shows the saved human pose name for a recognized pose id', () => {
    controller.subjects = [{
      id: 'sub-0',
      landmarks: Array.from({ length: 33 }, (_, index) => ({
        x: 0.2 + index * 0.01,
        y: 0.1 + index * 0.01,
        z: 0,
        visibility: 0.95,
      })),
    }]
    controller.socket.recognition = {
      'sub-0': { label: 'h1', confidence: 0.92 },
    }

    const { container } = renderStudio()

    const recognitionReadout = container.querySelector('.recognition-readout')
    expect(recognitionReadout).not.toBeNull()
    expect(within(recognitionReadout as HTMLElement).getByText('Hands up')).toBeVisible()
    expect(within(recognitionReadout as HTMLElement).queryByText('h1')).not.toBeInTheDocument()
  })

  it('contains no CJK production copy', () => {
    const { container } = renderStudio()
    expect(container.textContent).not.toMatch(/[\u3400-\u9fff]/)
  })

  it('starts with the computer camera on and lets the user turn it off', async () => {
    const user = userEvent.setup()
    renderStudio()

    const camera = screen.getByRole('switch', { name: 'Computer Camera' })
    expect(camera).toBeChecked()

    await user.click(camera)

    expect(controller.setCameraEnabled).toHaveBeenCalledWith(false)
  })

  it('resets the simulator from Live Preview', async () => {
    const user = userEvent.setup()
    renderStudio()

    await user.click(screen.getByRole('button', { name: 'Reset Simulator' }))

    expect(controller.resetSimulator).toHaveBeenCalledOnce()
  })

  it('previews a saved sequence directly from its library block', async () => {
    const user = userEvent.setup()
    controller.previewSequence.mockResolvedValueOnce({ status: 'completed' })
    renderStudio()

    await user.click(screen.getByRole('button', { name: 'Play sequence Celebrate' }))

    expect(controller.previewSequence).toHaveBeenCalledWith('s1')
    expect(await screen.findByText('Sequence preview complete')).toBeVisible()
  })

  it('loads and updates a saved sequence from its library block', async () => {
    const user = userEvent.setup()
    renderStudio()

    await user.click(screen.getByRole('button', { name: 'Celebrate, 1 step' }))

    const name = screen.getByRole('textbox', { name: 'Sequence name' })
    expect(name).toHaveValue('Celebrate')
    expect(screen.getByText('Wave', { selector: '.sequence-editor strong' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Update sequence' })).toBeVisible()

    await user.clear(name)
    await user.type(name, 'Welcome')
    const hold = screen.getByRole('spinbutton', { name: /Hold/i })
    await user.clear(hold)
    await user.type(hold, '900')
    await user.click(screen.getByRole('button', { name: 'Update sequence' }))

    expect(controller.updateSequence).toHaveBeenCalledWith(
      's1',
      'Welcome',
      [expect.objectContaining({ robotPoseId: 'r1', holdMs: 900, transitionMs: 300 })],
    )
  })

  it('cancels sequence editing and returns to a blank composer', async () => {
    const user = userEvent.setup()
    renderStudio()

    await user.click(screen.getByRole('button', { name: 'Celebrate, 1 step' }))
    await user.click(screen.getByRole('button', { name: 'Cancel edit' }))

    expect(screen.getByRole('textbox', { name: 'Sequence name' })).toHaveValue('')
    expect(screen.getByText('Drag robot poses here to build a response.')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Save sequence' })).toBeVisible()
  })

  it('previews a robot pose when its library card is selected', async () => {
    const user = userEvent.setup()
    controller.previewRobotPose.mockResolvedValueOnce({ status: 'completed' })
    renderStudio()

    await user.click(screen.getByRole('button', { name: 'Wave, Robot keyframe' }))

    expect(controller.setSelected).toHaveBeenCalledWith('robot', 'r1')
    expect(controller.previewRobotPose).toHaveBeenCalledWith('r1')
  })

  it('explains that collision warnings are allowed only in simulator preview', async () => {
    const user = userEvent.setup()
    controller.previewSequence.mockResolvedValueOnce({
      status: 'completed',
      reason: 'collision_risk',
    })
    renderStudio()

    await user.click(screen.getByRole('button', { name: 'Play sequence Celebrate' }))

    expect(await screen.findByText(
      'Sequence preview complete with simulator-only collision warning',
    )).toBeVisible()
  })

  it('separates trigger listening from direct sequence playback', async () => {
    const user = userEvent.setup()
    controller.selectedId = 's1'
    controller.previewSequence.mockResolvedValueOnce({ status: 'completed' })
    controller.setTriggerEnabled.mockResolvedValueOnce(undefined)
    renderStudio()

    await user.click(screen.getByRole('button', { name: 'Start Trigger Mode' }))
    expect(controller.setTriggerEnabled).toHaveBeenCalledWith(true)

    await user.click(screen.getByRole('button', { name: 'Play Celebrate' }))
    expect(controller.previewSequence).toHaveBeenCalledWith('s1')
  })

  it('deletes saved human and robot poses from the library', async () => {
    const user = userEvent.setup()
    controller.deleteHumanPose.mockResolvedValueOnce(undefined)
    controller.deleteRobotPose.mockResolvedValueOnce(undefined)
    renderStudio()

    await user.click(screen.getByRole('button', { name: 'Delete human pose Hands up' }))
    await user.click(screen.getByRole('button', { name: 'Delete robot pose Wave' }))

    expect(controller.deleteHumanPose).toHaveBeenCalledWith('h1')
    expect(controller.deleteRobotPose).toHaveBeenCalledWith('r1')
  })

  it('opens a focused human and robot pose capture workspace', async () => {
    const user = userEvent.setup()
    renderStudio()

    await user.click(screen.getByRole('button', { name: '+ Capture pose' }))

    const workspace = screen.getByRole('dialog', { name: 'Pose Capture' })
    expect(workspace).toBeVisible()
    expect(within(workspace).getByRole('img', { name: 'Live human pose' })).toHaveAttribute(
      'src',
      'http://localhost:8001/video_feed?overlay=upper_body',
    )
    expect(within(workspace).getByText('Simulator viewport')).toBeVisible()
    expect(controller.enterRobotPoseCapture).toHaveBeenCalledOnce()
    expect(await within(workspace).findByText('Robot is following you')).toBeVisible()
  })

  it('returns to passive multi-person tracking when Pose Capture closes', async () => {
    const user = userEvent.setup()
    renderStudio()

    await user.click(screen.getByRole('button', { name: '+ Capture pose' }))
    await screen.findByText('Robot is following you')
    await user.click(screen.getByRole('button', { name: 'Close pose capture' }))

    const sessionId = controller.enterRobotPoseCapture.mock.calls[0][0]
    expect(sessionId).toEqual(expect.any(String))
    expect(controller.exitRobotPoseCapture).toHaveBeenCalledWith(sessionId)
  })

  it('waits for a pending capture-mode entry before restoring passive tracking', async () => {
    let finishEntering: (() => void) | undefined
    controller.enterRobotPoseCapture.mockImplementationOnce(() => new Promise<void>((resolve) => {
      finishEntering = resolve
    }))
    const user = userEvent.setup()
    renderStudio()

    await user.click(screen.getByRole('button', { name: '+ Capture pose' }))
    await user.click(screen.getByRole('button', { name: 'Close pose capture' }))

    expect(controller.exitRobotPoseCapture).not.toHaveBeenCalled()
    const sessionId = controller.enterRobotPoseCapture.mock.calls[0][0]
    finishEntering?.()
    await waitFor(() => expect(controller.exitRobotPoseCapture).toHaveBeenCalledWith(sessionId))
  })

  it('binds a delayed close to its original capture session after reopening', async () => {
    let finishFirstEntry: (() => void) | undefined
    controller.enterRobotPoseCapture
      .mockImplementationOnce(() => new Promise<void>((resolve) => {
        finishFirstEntry = resolve
      }))
      .mockResolvedValueOnce(undefined)
    const user = userEvent.setup()
    renderStudio()

    await user.click(screen.getByRole('button', { name: '+ Capture pose' }))
    await user.click(screen.getByRole('button', { name: 'Close pose capture' }))
    await user.click(screen.getByRole('button', { name: '+ Capture pose' }))
    await waitFor(() => expect(controller.enterRobotPoseCapture).toHaveBeenCalledTimes(2))
    const firstSessionId = controller.enterRobotPoseCapture.mock.calls[0][0]
    const secondSessionId = controller.enterRobotPoseCapture.mock.calls[1][0]
    expect(firstSessionId).not.toBe(secondSessionId)
    finishFirstEntry?.()

    await waitFor(() => expect(controller.exitRobotPoseCapture).toHaveBeenCalledWith(firstSessionId))
    expect(screen.getByRole('dialog', { name: 'Pose Capture' })).toBeVisible()
  })

  it('restores passive tracking when capture entry applies but its response is lost', async () => {
    controller.enterRobotPoseCapture.mockRejectedValueOnce(new Error('Connection lost'))
    const user = userEvent.setup()
    renderStudio()

    await user.click(screen.getByRole('button', { name: '+ Capture pose' }))
    expect(await screen.findByText('Connection lost')).toBeVisible()
    const sessionId = controller.enterRobotPoseCapture.mock.calls[0][0]
    await user.click(screen.getByRole('button', { name: 'Close pose capture' }))

    await waitFor(() => expect(controller.exitRobotPoseCapture).toHaveBeenCalledWith(sessionId))
  })

  it('cleans up the active capture session when a reset entry fails', async () => {
    const user = userEvent.setup()
    renderStudio()

    await user.click(screen.getByRole('button', { name: '+ Capture pose' }))
    await screen.findByText('Robot is following you')
    const activeSessionId = controller.enterRobotPoseCapture.mock.calls[0][0]
    controller.enterRobotPoseCapture.mockRejectedValueOnce(new Error('Reset tracking failed'))

    await user.click(screen.getByRole('button', { name: 'Reset Simulator' }))
    expect(await screen.findByText('Reset tracking failed')).toBeVisible()
    const failedSessionId = controller.enterRobotPoseCapture.mock.calls[1][0]
    await user.click(screen.getByRole('button', { name: 'Close pose capture' }))

    await waitFor(() => {
      expect(controller.exitRobotPoseCapture).toHaveBeenCalledWith(activeSessionId)
      expect(controller.exitRobotPoseCapture).toHaveBeenCalledWith(failedSessionId)
    })
  })

  it('resets and pauses before the first Teach Robot mirror command', async () => {
    const user = userEvent.setup()
    controller.resetSimulator.mockClear()
    controller.mirrorRobotPose.mockClear()
    renderStudio()

    await user.click(screen.getByRole('button', { name: '+ Capture pose' }))

    expect(controller.resetSimulator).toHaveBeenCalledOnce()
    expect(controller.mirrorRobotPose).not.toHaveBeenCalled()
    expect(screen.getByText('Preparing simulator…')).toBeVisible()
    await screen.findByText('Robot is following you')
    expect(controller.mirrorRobotPose).toHaveBeenCalled()
  })

  it('resets the simulator from Pose Capture and resumes after the preparation pause', async () => {
    const user = userEvent.setup()
    renderStudio()

    await user.click(screen.getByRole('button', { name: '+ Capture pose' }))
    await screen.findByText('Robot is following you')
    controller.resetSimulator.mockClear()
    controller.mirrorRobotPose.mockClear()
    let finishReset: (() => void) | undefined
    controller.resetSimulator.mockImplementationOnce(() => new Promise<boolean>((resolve) => {
      finishReset = () => resolve(true)
    }))
    await user.click(screen.getByRole('button', { name: 'Reset Simulator' }))

    expect(controller.resetSimulator).toHaveBeenCalledOnce()
    expect(screen.getByRole('dialog', { name: 'Pose Capture' })).toBeVisible()
    expect(
      controller.mirrorRobotPose.mock.calls.every(([signal]) => signal?.aborted),
    ).toBe(true)
    expect(screen.getByText('Preparing simulator…')).toBeVisible()
    finishReset?.()
    await screen.findByText('Robot is following you')
    expect(controller.mirrorRobotPose).toHaveBeenCalled()
  })

  it('stops an in-flight live mirror before resetting Pose Capture', async () => {
    let mirrorSignal: AbortSignal | undefined
    controller.mirrorRobotPose.mockImplementationOnce((signal?: AbortSignal) => {
      mirrorSignal = signal
      return new Promise(() => undefined)
    })
    const user = userEvent.setup()
    renderStudio()

    await user.click(screen.getByRole('button', { name: '+ Capture pose' }))
    await waitFor(() => expect(mirrorSignal).toBeDefined())
    controller.resetSimulator.mockClear()
    controller.resetSimulator.mockImplementationOnce(async () => {
      expect(mirrorSignal?.aborted).toBe(true)
      return true
    })
    await user.click(screen.getByRole('button', { name: 'Reset Simulator' }))

    expect(controller.resetSimulator).toHaveBeenCalledOnce()
    expect(screen.getByRole('dialog', { name: 'Pose Capture' })).toBeVisible()
  })

  it('latches an actual fall and requires reset before mirroring can continue', async () => {
    const user = userEvent.setup()
    renderStudio()

    await user.click(screen.getByRole('button', { name: '+ Capture pose' }))
    await screen.findByText('Robot is following you')
    await user.click(screen.getByRole('button', { name: 'Simulate fall' }))

    expect(screen.getByRole('alert')).toHaveTextContent('Fall detected — mirroring stopped')
    expect(screen.getByRole('button', { name: 'Capture & Safety Check' })).toBeDisabled()
    controller.resetSimulator.mockClear()
    await user.click(screen.getByRole('button', { name: 'Reset Simulator' }))
    expect(controller.resetSimulator).toHaveBeenCalledOnce()
    expect(screen.getByText('Preparing simulator…')).toBeVisible()
    expect(await screen.findByText('Robot is following you')).toBeVisible()
  })

  it('opens a fresh human pose training session every time', async () => {
    const user = userEvent.setup()
    renderStudio()

    await user.click(screen.getByRole('button', { name: '+ Train pose' }))
    expect(screen.getByRole('dialog', { name: 'Train a human pose' })).toBeVisible()
    await user.type(screen.getByRole('textbox', { name: 'Pose name' }), 'New pose')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    await user.click(screen.getByRole('button', { name: '+ Train pose' }))
    expect(screen.getByRole('textbox', { name: 'Pose name' })).toHaveValue('')
    expect(screen.getByText('0 of 3 required samples accepted')).toBeVisible()
  })

  it('saves the latest safe pose shown by live mirroring', async () => {
    const user = userEvent.setup()
    controller.captureRobotPose.mockResolvedValueOnce({ id: 'captured-pose' })
    renderStudio()

    await user.click(screen.getByRole('button', { name: '+ Capture pose' }))
    await screen.findByText('Robot is following you')
    await user.type(screen.getByRole('textbox', { name: 'Robot pose name' }), 'Reach high')
    await user.click(screen.getByRole('button', { name: 'Capture & Safety Check' }))

    expect(controller.captureRobotPose).toHaveBeenCalledWith(
      'Reach high',
      { l_sho_pitch: 0.25, l_knee: 0.1 },
    )
  })

  it('explains when live mirroring is limited for safety', async () => {
    controller.mirrorRobotPose.mockResolvedValueOnce({
      status: 'done',
      targets: { l_sho_pitch: 0.1 },
      safety: {
        fall_blocked: false,
        collision_clamped: true,
        safe_fraction: 0.4,
        bad_pairs: ['arm<->torso'],
      },
    })
    const user = userEvent.setup()
    renderStudio()

    await user.click(screen.getByRole('button', { name: '+ Capture pose' }))

    expect(await screen.findByText('Safety limited')).toBeVisible()
    expect(screen.queryByText(/collision_risk/)).not.toBeInTheDocument()
  })

  it('describes leg rate limiting as fall prevention', async () => {
    controller.mirrorRobotPose.mockResolvedValueOnce({
      status: 'done',
      targets: { l_knee: 0.08 },
      safety: {
        fall_blocked: false,
        collision_clamped: false,
        rate_limited: true,
        safe_fraction: 1,
        bad_pairs: [],
      },
    })
    const user = userEvent.setup()
    renderStudio()

    await user.click(screen.getByRole('button', { name: '+ Capture pose' }))

    expect(await screen.findByText('Motion slowed')).toBeVisible()
    expect(screen.getByText(/reduce the chance of a fall/i)).toBeVisible()
    expect(screen.queryByText(/100%/)).not.toBeInTheDocument()
  })

  it('backs off when pose detection is unavailable', async () => {
    controller.mirrorRobotPose.mockRejectedValue(new Error('Step back into frame'))
    const user = userEvent.setup()
    renderStudio()

    await user.click(screen.getByRole('button', { name: '+ Capture pose' }))
    expect(await screen.findByText('Upper body not visible')).toBeVisible()
    await new Promise((resolve) => window.setTimeout(resolve, 250))

    expect(controller.mirrorRobotPose).toHaveBeenCalledTimes(1)
  })

  it('keeps the capture workspace open after saving so the result can be reviewed', async () => {
    const user = userEvent.setup()
    controller.captureRobotPose.mockResolvedValueOnce({ id: 'captured-pose' })
    renderStudio()

    await user.click(screen.getByRole('button', { name: '+ Capture pose' }))
    await screen.findByText('Robot is following you')
    await user.type(screen.getByRole('textbox', { name: 'Robot pose name' }), 'Reach high')
    await user.click(screen.getByRole('button', { name: 'Capture & Safety Check' }))

    expect(await screen.findByText('Pose saved and shown in the simulator')).toBeVisible()
    expect(screen.getByRole('dialog', { name: 'Pose Capture' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Done' })).toBeVisible()
  })

  it('starts a fresh capture after finishing a saved pose', async () => {
    const user = userEvent.setup()
    controller.captureRobotPose.mockResolvedValueOnce({ id: 'captured-pose' })
    renderStudio()

    await user.click(screen.getByRole('button', { name: '+ Capture pose' }))
    await screen.findByText('Robot is following you')
    await user.type(screen.getByRole('textbox', { name: 'Robot pose name' }), 'Reach high')
    await user.click(screen.getByRole('button', { name: 'Capture & Safety Check' }))
    await user.click(await screen.findByRole('button', { name: 'Done' }))
    await user.click(screen.getByRole('button', { name: '+ Capture pose' }))

    expect(screen.getByRole('button', { name: 'Capture & Safety Check' })).toBeVisible()
    expect(screen.queryByText('Pose saved and shown in the simulator')).not.toBeInTheDocument()
  })

  it('lets the user add another pose directly after saving', async () => {
    const user = userEvent.setup()
    controller.captureRobotPose.mockResolvedValueOnce({ id: 'captured-pose' })
    renderStudio()

    await user.click(screen.getByRole('button', { name: '+ Capture pose' }))
    await screen.findByText('Robot is following you')
    await user.type(screen.getByRole('textbox', { name: 'Robot pose name' }), 'Reach high')
    await user.click(screen.getByRole('button', { name: 'Capture & Safety Check' }))
    await user.click(await screen.findByRole('button', { name: 'Add New' }))

    const nameInput = screen.getByRole('textbox', { name: 'Robot pose name' })
    expect(nameInput).toHaveValue('')
    expect(nameInput).toHaveFocus()
    expect(screen.getByRole('button', { name: 'Capture & Safety Check' })).toBeVisible()
    expect(screen.queryByText('Pose saved and shown in the simulator')).not.toBeInTheDocument()
  })

  it('prevents closing the workspace while a capture is being saved', async () => {
    const user = userEvent.setup()
    controller.captureRobotPose.mockReturnValueOnce(new Promise(() => undefined))
    renderStudio()

    await user.click(screen.getByRole('button', { name: '+ Capture pose' }))
    await screen.findByText('Robot is following you')
    await user.type(screen.getByRole('textbox', { name: 'Robot pose name' }), 'Reach high')
    await user.click(screen.getByRole('button', { name: 'Capture & Safety Check' }))

    expect(screen.getByRole('button', { name: 'Close pose capture' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled()
  })
})
