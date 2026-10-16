import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { RuleCanvas } from './RuleCanvas'

describe('RuleCanvas', () => {
  it('creates an IF human pose THEN robot pose interaction', async () => {
    const onCreateRule = vi.fn()
    render(
      <RuleCanvas
        humanPoses={[{ id: 'h1', name: 'Hands up' }]}
        robotPoses={[{ id: 'r1', name: 'Wave' }]}
        rules={[]}
        onCreateRule={onCreateRule}
        onPreviewRobotPose={vi.fn()}
      />,
    )

    await userEvent.click(screen.getByRole('button', { name: 'Add Interaction' }))

    expect(onCreateRule).toHaveBeenCalledWith({
      humanPoseId: 'h1',
      robotPoseId: 'r1',
      cooldownSeconds: 2,
    })
  })

  it('renders numbered pose interactions and previews the robot pose', async () => {
    const onPreviewRobotPose = vi.fn()
    render(
      <RuleCanvas
        humanPoses={[{ id: 'h1', name: 'Clap', thumbnail_svg: '<svg></svg>' }]}
        robotPoses={[{ id: 'r1', name: 'Wave' }]}
        rules={[{ id: 'rule-1', human_pose_id: 'h1', sequence_id: 's1', robot_pose_id: 'r1' }]}
        onCreateRule={vi.fn()}
        onPreviewRobotPose={onPreviewRobotPose}
      />,
    )

    expect(screen.getByRole('heading', { name: 'Interaction Sequencer' })).toBeVisible()
    expect(screen.getByText('1')).toBeVisible()
    expect(screen.getByRole('img', { name: 'Human pose Clap' })).toBeVisible()

    await userEvent.click(screen.getByRole('button', { name: 'Play CoRAL response Wave' }))

    expect(onPreviewRobotPose).toHaveBeenCalledWith('r1')
  })

  it('selects the first interaction choices when project data loads asynchronously', async () => {
    const onCreateRule = vi.fn()
    const { rerender } = render(
      <RuleCanvas
        humanPoses={[]}
        robotPoses={[]}
        rules={[]}
        onCreateRule={onCreateRule}
        onPreviewRobotPose={vi.fn()}
      />,
    )

    rerender(
      <RuleCanvas
        humanPoses={[{ id: 'h1', name: 'Clap' }]}
        robotPoses={[{ id: 'r1', name: 'Wave' }]}
        rules={[]}
        onCreateRule={onCreateRule}
        onPreviewRobotPose={vi.fn()}
      />,
    )

    const add = screen.getByRole('button', { name: 'Add Interaction' })
    expect(add).toBeEnabled()
    await userEvent.click(add)
    expect(onCreateRule).toHaveBeenCalledWith({
      humanPoseId: 'h1',
      robotPoseId: 'r1',
      cooldownSeconds: 2,
    })
  })

  it('reorders saved interactions with accessible move controls', async () => {
    const onReorderRules = vi.fn()
    render(
      <RuleCanvas
        humanPoses={[{ id: 'h1', name: 'Clap' }, { id: 'h2', name: 'Hands up' }]}
        robotPoses={[{ id: 'r1', name: 'Wave' }, { id: 'r2', name: 'Cross arms' }]}
        rules={[
          { id: 'rule-1', human_pose_id: 'h1', sequence_id: 's1', robot_pose_id: 'r1' },
          { id: 'rule-2', human_pose_id: 'h2', sequence_id: 's2', robot_pose_id: 'r2' },
        ]}
        onCreateRule={vi.fn()}
        onPreviewRobotPose={vi.fn()}
        onDeleteRule={vi.fn()}
        onReorderRules={onReorderRules}
      />,
    )

    await userEvent.click(screen.getByRole('button', { name: 'Move interaction 1 down' }))

    expect(onReorderRules).toHaveBeenCalledWith(['rule-2', 'rule-1'])
  })

  it('reorders saved interactions by dragging the handle', () => {
    const onReorderRules = vi.fn()
    render(
      <RuleCanvas
        humanPoses={[{ id: 'h1', name: 'Clap' }, { id: 'h2', name: 'Hands up' }]}
        robotPoses={[{ id: 'r1', name: 'Wave' }, { id: 'r2', name: 'Cross arms' }]}
        rules={[
          { id: 'rule-1', human_pose_id: 'h1', sequence_id: 's1', robot_pose_id: 'r1' },
          { id: 'rule-2', human_pose_id: 'h2', sequence_id: 's2', robot_pose_id: 'r2' },
        ]}
        onCreateRule={vi.fn()}
        onPreviewRobotPose={vi.fn()}
        onDeleteRule={vi.fn()}
        onReorderRules={onReorderRules}
      />,
    )

    fireEvent.dragStart(screen.getByLabelText('Drag interaction 1'))
    fireEvent.drop(screen.getByTestId('interaction-rule-2'))

    expect(onReorderRules).toHaveBeenCalledWith(['rule-2', 'rule-1'])
  })

  it('confirms before deleting a saved interaction', async () => {
    const onDeleteRule = vi.fn()
    vi.spyOn(window, 'confirm').mockReturnValueOnce(true)
    render(
      <RuleCanvas
        humanPoses={[{ id: 'h1', name: 'Clap' }]}
        robotPoses={[{ id: 'r1', name: 'Wave' }]}
        rules={[{ id: 'rule-1', human_pose_id: 'h1', sequence_id: 's1', robot_pose_id: 'r1' }]}
        onCreateRule={vi.fn()}
        onPreviewRobotPose={vi.fn()}
        onDeleteRule={onDeleteRule}
        onReorderRules={vi.fn()}
      />,
    )

    await userEvent.click(screen.getByRole('button', { name: 'Delete interaction 1' }))

    expect(onDeleteRule).toHaveBeenCalledWith('rule-1')
  })
})
