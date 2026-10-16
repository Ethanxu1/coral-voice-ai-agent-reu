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

  it('uses the clearest upper body automatically and does not ask for a subject', async () => {
    const incomplete = landmarks()
    incomplete[27].visibility = 0.1
    const clearer = landmarks()
    clearer[15].x = 0.91
    incomplete[11].visibility = 0.55
    const api = {
      createHumanPose: vi.fn().mockResolvedValue({ id: 'pose-1' }),
      addHumanPoseSample: vi.fn().mockResolvedValue({ id: 'sample' }),
    }
    render(
      <PoseTrainingDialog
        open
        projectId="project-1"
        existingNames={[]}
        subjects={[
          { id: 'person-1', landmarks: incomplete },
          { id: 'person-2', landmarks: clearer },
        ]}
        api={api}
        onSaved={vi.fn()}
        onClose={vi.fn()}
      />,
    )

    expect(screen.queryByRole('combobox', { name: 'Person' })).not.toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Current upper-body skeleton' })).toBeVisible()
    await userEvent.type(screen.getByLabelText('Pose name'), 'Hands up')
    const capture = screen.getByRole('button', { name: 'Capture sample' })
    await userEvent.click(capture)
    await userEvent.click(capture)
    await userEvent.click(capture)
    await userEvent.click(screen.getByRole('button', { name: 'Save human pose' }))

    expect(api.addHumanPoseSample).toHaveBeenCalledTimes(3)
    expect(api.addHumanPoseSample).toHaveBeenCalledWith(
      'pose-1',
      expect.arrayContaining([expect.objectContaining({ x: 0.91 })]),
    )
  })

  it('prefers a fully visible person over a higher-average occluded person', async () => {
    const occluded = landmarks()
    occluded.forEach((landmark) => { landmark.visibility = 1 })
    occluded[15].visibility = 0.49
    occluded[15].x = 0.11
    const valid = landmarks()
    valid.forEach((landmark) => { landmark.visibility = 0.8 })
    valid[15].x = 0.88
    const api = {
      createHumanPose: vi.fn().mockResolvedValue({ id: 'pose-1' }),
      addHumanPoseSample: vi.fn().mockResolvedValue({ id: 'sample' }),
    }
    render(
      <PoseTrainingDialog
        open
        projectId="project-1"
        existingNames={[]}
        subjects={[
          { id: 'occluded', landmarks: occluded },
          { id: 'valid', landmarks: valid },
        ]}
        api={api}
        onSaved={vi.fn()}
        onClose={vi.fn()}
      />,
    )

    await userEvent.type(screen.getByLabelText('Pose name'), 'Reach')
    const capture = screen.getByRole('button', { name: 'Capture sample' })
    await userEvent.click(capture)
    await userEvent.click(capture)
    await userEvent.click(capture)
    await userEvent.click(screen.getByRole('button', { name: 'Save human pose' }))

    expect(api.addHumanPoseSample).toHaveBeenCalledWith(
      'pose-1',
      expect.arrayContaining([expect.objectContaining({ x: 0.88 })]),
    )
  })
})
