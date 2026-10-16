import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import RobotViewer from './RobotViewer'

vi.mock('@react-three/fiber', () => ({
  Canvas: () => <div data-testid="canvas" />,
  useFrame: vi.fn(),
}))
vi.mock('@react-three/drei', () => ({
  Grid: () => null,
  OrbitControls: () => null,
}))

class FakeWebSocket {
  static instance: FakeWebSocket | null = null
  binaryType = ''
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: (() => void) | null = null

  constructor(_url: string) {
    FakeWebSocket.instance = this
  }

  close() {}
}

describe('RobotViewer fall alarm', () => {
  beforeEach(() => {
    vi.stubGlobal('WebSocket', FakeWebSocket)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    FakeWebSocket.instance = null
  })

  it('shows an alarm when the simulator reports an actual fall', async () => {
    render(<RobotViewer embedded />)

    await act(async () => {
      FakeWebSocket.instance?.onmessage?.({
        data: JSON.stringify({
          type: 'stability',
          fallen: true,
          head_z: 0.12,
          threshold_z: 0.25,
        }),
      })
    })

    expect(screen.getByRole('alert')).toHaveTextContent('Fall detected')
  })

  it('reports live fall-state changes to its parent workspace', async () => {
    const onStabilityChange = vi.fn()
    render(<RobotViewer embedded onStabilityChange={onStabilityChange} />)

    await act(async () => {
      FakeWebSocket.instance?.onmessage?.({
        data: JSON.stringify({
          type: 'stability',
          fallen: true,
          head_z: 0.12,
          threshold_z: 0.25,
        }),
      })
    })

    expect(onStabilityChange).toHaveBeenCalledWith(true)
  })

  it('does not replay the sound while the fall threshold chatters', async () => {
    const createdContexts: object[] = []
    class FakeAudioContext {
      currentTime = 0
      destination = {}
      createOscillator = () => ({
        type: 'square',
        frequency: { setValueAtTime: vi.fn() },
        connect: vi.fn(),
        start: vi.fn(),
        stop: vi.fn(),
        onended: null,
      })
      createGain = () => ({
        gain: { setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() },
        connect: vi.fn(),
      })
      resume = () => Promise.resolve()
      close = () => Promise.resolve()

      constructor() {
        createdContexts.push(this)
      }
    }
    vi.stubGlobal('AudioContext', FakeAudioContext)
    render(<RobotViewer embedded />)

    for (const fallen of [true, false, true]) {
      await act(async () => {
        FakeWebSocket.instance?.onmessage?.({
          data: JSON.stringify({ type: 'stability', fallen, head_z: 0.2, threshold_z: 0.25 }),
        })
      })
    }

    expect(createdContexts).toHaveLength(1)
  })
})
