import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { BlockLibrary } from './BlockLibrary'

describe('BlockLibrary', () => {
  it('groups reusable blocks and reports selection', async () => {
    const onSelect = vi.fn()
    render(
      <BlockLibrary
        humanPoses={[{ id: 'h1', name: 'Hands up' }]}
        robotPoses={[{ id: 'r1', name: 'Wave' }]}
        sequences={[{ id: 's1', name: 'Friendly hello', steps: [{}, {}] }]}
        onSelect={onSelect}
        onTrainHumanPose={vi.fn()}
        onCaptureRobotPose={vi.fn()}
        onCreateSequence={vi.fn()}
      />,
    )

    expect(screen.getByText('Human Poses')).toBeInTheDocument()
    expect(screen.getByText('Robot Poses')).toBeInTheDocument()
    expect(screen.getByText('2 steps')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Hands up/ }))
    expect(onSelect).toHaveBeenCalledWith('human', 'h1')
  })
})
