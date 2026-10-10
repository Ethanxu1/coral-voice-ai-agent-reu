import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { LivePreview } from './LivePreview'
import type { Landmark } from './types'

vi.mock('../components/RobotViewer', () => ({ default: () => <div>Simulator viewport</div> }))

const landmarks: Landmark[] = Array.from({ length: 33 }, (_, index) => ({
  x: 0.2 + index * 0.01,
  y: 0.1 + index * 0.02,
  z: 0,
  visibility: 0.95,
}))

describe('LivePreview', () => {
  it('shows the computer camera stream while the camera is on', () => {
    render(
      <LivePreview
        subjects={[]}
        recognition={{}}
        holds={{}}
        executingSequenceId={null}
        statusMessage={null}
        cameraEnabled
      />,
    )

    expect(screen.getByRole('img', { name: 'Computer camera preview' })).toHaveAttribute(
      'src',
      'http://localhost:8001/video_feed',
    )
  })

  it('shows the winning person, confidence, hold progress, and full skeleton', () => {
    render(
      <LivePreview
        subjects={[{ id: 'person-2', landmarks }]}
        recognition={{ 'person-2': { label: 'Hands up', confidence: 0.82 } }}
        holds={{ 'person-2': 0.86 }}
        executingSequenceId={null}
        statusMessage="Safety check passed"
        cameraEnabled
      />,
    )

    expect(screen.getByText('Person person-2')).toBeInTheDocument()
    expect(screen.getByText('82%')).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '86')
    expect(screen.getByTestId('bone-left-knee-left-ankle')).toBeInTheDocument()
  })

  it('hides stale recognition when the computer camera is off', () => {
    render(
      <LivePreview
        subjects={[{ id: 'person-2', landmarks }]}
        recognition={{ 'person-2': { label: 'Hands up', confidence: 0.82 } }}
        holds={{ 'person-2': 0.86 }}
        executingSequenceId={null}
        statusMessage={null}
        cameraEnabled={false}
      />,
    )

    expect(screen.getByText('Computer camera is off')).toBeVisible()
    expect(screen.queryByText('Person person-2')).not.toBeInTheDocument()
    expect(screen.queryByRole('img', { name: 'Computer camera preview' })).not.toBeInTheDocument()
  })

  it('lets the user expand the complete live preview to fullscreen', async () => {
    const user = userEvent.setup()
    const requestFullscreen = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(HTMLElement.prototype, 'requestFullscreen', {
      configurable: true,
      value: requestFullscreen,
    })

    render(
      <LivePreview
        subjects={[]}
        recognition={{}}
        holds={{}}
        executingSequenceId={null}
        statusMessage={null}
        cameraEnabled
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Expand Live Preview' }))

    expect(requestFullscreen).toHaveBeenCalledOnce()
  })

  it('reports when the browser rejects fullscreen mode', async () => {
    const user = userEvent.setup()
    Object.defineProperty(HTMLElement.prototype, 'requestFullscreen', {
      configurable: true,
      value: vi.fn().mockRejectedValue(new Error('Fullscreen denied')),
    })

    render(
      <LivePreview
        subjects={[]}
        recognition={{}}
        holds={{}}
        executingSequenceId={null}
        statusMessage={null}
        cameraEnabled
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Expand Live Preview' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Fullscreen is not available')
  })
})
