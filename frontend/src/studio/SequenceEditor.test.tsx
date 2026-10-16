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

  it('rounds and clamps edited timing values to the API range', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<SequenceEditor steps={steps.slice(0, 1)} onChange={onChange} />)

    const hold = screen.getByRole('spinbutton', { name: /Hold/i })
    await user.clear(hold)
    await user.type(hold, '70000.4')
    await user.tab()

    expect(onChange.mock.calls[onChange.mock.calls.length - 1][0][0].holdMs).toBe(60000)
    expect(hold).toHaveValue(60000)

    const transition = screen.getByRole('spinbutton', { name: /Transition/i })
    await user.clear(transition)
    await user.type(transition, '725.7')
    await user.tab()

    expect(onChange.mock.calls[onChange.mock.calls.length - 1][0][0].transitionMs).toBe(726)
    expect(transition).toHaveValue(726)
  })
})
