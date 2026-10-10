import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { SequenceEditor, type EditableSequenceStep } from './SequenceEditor'

const steps: EditableSequenceStep[] = [
  { id: 'wave', robotPoseId: 'r1', poseName: 'Wave', holdMs: 800, transitionMs: 300 },
  { id: 'stand', robotPoseId: 'r2', poseName: 'Stand', holdMs: 700, transitionMs: 300 },
  { id: 'crouch', robotPoseId: 'r3', poseName: 'Crouch', holdMs: 1000, transitionMs: 400 },
]

describe('SequenceEditor', () => {
  it('reorders sequence steps and keeps timings with their blocks', async () => {
    const onChange = vi.fn()
    render(<SequenceEditor steps={steps} onChange={onChange} />)

    const moveUp = screen.getByRole('button', { name: 'Move Crouch up' })
    await userEvent.click(moveUp)
    await userEvent.click(moveUp)

    expect(onChange).toHaveBeenLastCalledWith([
      expect.objectContaining({ poseName: 'Crouch', holdMs: 1000 }),
      expect.objectContaining({ poseName: 'Wave', holdMs: 800 }),
      expect.objectContaining({ poseName: 'Stand', holdMs: 700 }),
    ])
  })
})
