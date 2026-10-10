import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { PoseTrainingDialog } from './PoseTrainingDialog'
import type { Landmark } from './types'

function landmarks(): Landmark[] {
  return Array.from({ length: 33 }, (_, index) => ({
    x: 0.2 + index * 0.01,
    y: 0.1 + index * 0.02,
    z: 0,
    visibility: 0.95,
  }))
}

describe('PoseTrainingDialog', () => {
  it('requires three accepted samples before saving', async () => {
    const api = {
      createHumanPose: vi.fn().mockResolvedValue({ id: 'pose-1' }),
      addHumanPoseSample: vi.fn().mockResolvedValue({ id: 'sample' }),
    }
    render(
      <PoseTrainingDialog
        open
        projectId="project-1"
        existingNames={[]}
        subjects={[{ id: 'person-1', landmarks: landmarks() }]}
        api={api}
        onSaved={vi.fn()}
        onClose={vi.fn()}
      />,
    )
    await userEvent.type(screen.getByLabelText('Pose name'), 'Hands up')
    const capture = screen.getByRole('button', { name: 'Capture sample' })

    await userEvent.click(capture)
    await userEvent.click(capture)
    expect(screen.getByRole('button', { name: 'Save human pose' })).toBeDisabled()
    await userEvent.click(capture)
    expect(screen.getByRole('button', { name: 'Save human pose' })).toBeEnabled()
  })

  it('rejects a sample when an ankle is not visible', async () => {
    const incomplete = landmarks()
    incomplete[27].visibility = 0.1
    render(
      <PoseTrainingDialog
        open
        projectId="project-1"
        existingNames={[]}
        subjects={[{ id: 'person-1', landmarks: incomplete }]}
        api={{ createHumanPose: vi.fn(), addHumanPoseSample: vi.fn() }}
        onSaved={vi.fn()}
        onClose={vi.fn()}
      />,
    )

    await userEvent.click(screen.getByRole('button', { name: 'Capture sample' }))
    expect(screen.getByText('Full body not visible')).toBeInTheDocument()
  })
})
