import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { BlockLibrary } from './BlockLibrary'

describe('BlockLibrary', () => {
  it('groups reusable blocks and reports selection', async () => {
    const onSelect = vi.fn()
    const onDeleteHumanPose = vi.fn()
    const onDeleteRobotPose = vi.fn()
    const onPreviewSequence = vi.fn()
    const onPreviewRobotPose = vi.fn()
    render(
      <BlockLibrary
        humanPoses={[{ id: 'h1', name: 'Hands up' }]}
        robotPoses={[{ id: 'r1', name: 'Wave' }]}
        sequences={[{ id: 's1', name: 'Friendly hello', steps: [{}, {}] }]}
        onSelect={onSelect}
        onTrainHumanPose={vi.fn()}
        onCaptureRobotPose={vi.fn()}
        onCreateSequence={vi.fn()}
        onDeleteHumanPose={onDeleteHumanPose}
        onDeleteRobotPose={onDeleteRobotPose}
        onPreviewSequence={onPreviewSequence}
        onPreviewRobotPose={onPreviewRobotPose}
      />,
    )

    expect(screen.getByText('Human Poses')).toBeInTheDocument()
    expect(screen.getByText('Robot Poses')).toBeInTheDocument()
    expect(screen.getByText('2 steps')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Hands up, Learned trigger' }))
    expect(onSelect).toHaveBeenCalledWith('human', 'h1')

    await userEvent.click(screen.getByRole('button', { name: 'Delete human pose Hands up' }))
    expect(onDeleteHumanPose).toHaveBeenCalledWith('h1')

    await userEvent.click(screen.getByRole('button', { name: 'Delete robot pose Wave' }))
    expect(onDeleteRobotPose).toHaveBeenCalledWith('r1')

    await userEvent.click(screen.getByRole('button', { name: 'Wave, Robot keyframe' }))
    expect(onPreviewRobotPose).toHaveBeenCalledWith('r1')

    await userEvent.click(screen.getByRole('button', { name: 'Play sequence Friendly hello' }))
    expect(onPreviewSequence).toHaveBeenCalledWith('s1')
  })

  it('disables simulator preview controls while another preview is running', () => {
    render(
      <BlockLibrary
        humanPoses={[]}
        robotPoses={[{ id: 'r1', name: 'Wave' }]}
        sequences={[{ id: 's1', name: 'Greeting', steps: [{}] }]}
        previewBusy
        onSelect={vi.fn()}
        onTrainHumanPose={vi.fn()}
        onCaptureRobotPose={vi.fn()}
        onCreateSequence={vi.fn()}
        onDeleteHumanPose={vi.fn()}
        onDeleteRobotPose={vi.fn()}
        onPreviewRobotPose={vi.fn()}
        onPreviewSequence={vi.fn()}
      />,
    )

    expect(screen.getByRole('button', { name: 'Wave, Robot keyframe' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Play sequence Greeting' })).toBeDisabled()
  })

  it('collapses and expands the human and robot pose libraries', async () => {
    render(
      <BlockLibrary
        humanPoses={[{ id: 'h1', name: 'Hands up' }]}
        robotPoses={[{ id: 'r1', name: 'Wave' }]}
        sequences={[]}
        onSelect={vi.fn()}
        onTrainHumanPose={vi.fn()}
        onCaptureRobotPose={vi.fn()}
        onCreateSequence={vi.fn()}
        onDeleteHumanPose={vi.fn()}
        onDeleteRobotPose={vi.fn()}
        onPreviewRobotPose={vi.fn()}
        onPreviewSequence={vi.fn()}
      />,
    )

    await userEvent.click(screen.getByRole('button', { name: 'Collapse Human Poses' }))
    expect(screen.queryByRole('button', { name: 'Hands up, Learned trigger' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Expand Human Poses' }))
    expect(screen.getByRole('button', { name: 'Hands up, Learned trigger' })).toBeVisible()

    await userEvent.click(screen.getByRole('button', { name: 'Collapse Robot Poses' }))
    expect(screen.queryByRole('button', { name: 'Wave, Robot keyframe' })).not.toBeInTheDocument()
  })
})
