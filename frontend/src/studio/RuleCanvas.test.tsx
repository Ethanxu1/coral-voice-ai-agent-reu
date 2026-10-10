import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { RuleCanvas } from './RuleCanvas'

describe('RuleCanvas', () => {
  it('creates an IF human pose THEN sequence rule', async () => {
    const onCreateRule = vi.fn()
    render(
      <RuleCanvas
        humanPoses={[{ id: 'h1', name: 'Hands up' }]}
        sequences={[{ id: 's1', name: 'Friendly wave' }]}
        rules={[]}
        onCreateRule={onCreateRule}
      />,
    )

    await userEvent.click(screen.getByRole('button', { name: 'Add rule' }))

    expect(onCreateRule).toHaveBeenCalledWith({
      humanPoseId: 'h1',
      sequenceId: 's1',
      cooldownSeconds: 2,
    })
  })
})
