import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import MotionStudio from './MotionStudio'

const controller = {
  projects: [{ id: 'p1', name: 'Classroom' }],
  activeProjectId: 'p1',
  setActiveProjectId: vi.fn(),
  humanPoses: [{ id: 'h1', name: 'Hands up' }],
  robotPoses: [{ id: 'r1', name: 'Wave' }],
  sequences: [{ id: 's1', name: 'Celebrate', steps: [] }],
  rules: [],
  selectedId: null,
  setSelected: vi.fn(),
  trainingOpen: false,
  setTrainingOpen: vi.fn(),
  subjects: [],
  trainingApi: { createHumanPose: vi.fn(), addHumanPoseSample: vi.fn() },
  refresh: vi.fn(),
  createRule: vi.fn(),
  createSequence: vi.fn(),
  previewSequence: vi.fn(),
  captureRobotPose: vi.fn(),
  importProject: vi.fn(),
  exportProject: vi.fn(),
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
vi.mock('../components/RobotViewer', () => ({ default: () => <div>Simulator viewport</div> }))

describe('MotionStudio', () => {
  beforeEach(() => vi.clearAllMocks())

  const renderStudio = () => render(
    <MemoryRouter>
      <MotionStudio />
    </MemoryRouter>,
  )

  it('defaults to simulator and renders the three columns', () => {
    renderStudio()

    expect(screen.getByRole('heading', { name: 'Block Library' })).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Rule Canvas' })).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Live Preview' })).toBeVisible()
    expect(screen.getByText('Simulator')).toBeVisible()
    expect(screen.getByRole('switch', { name: 'Live Robot' })).not.toBeChecked()
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
})
