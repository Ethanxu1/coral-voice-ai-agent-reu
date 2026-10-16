import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useStudioSocket } from './useStudioSocket'

class MockWebSocket {
  static instances: MockWebSocket[] = []
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  sent: string[] = []

  constructor(public url: string) {
    MockWebSocket.instances.push(this)
  }

  send(data: string) {
    this.sent.push(data)
  }

  close() {}
}

describe('useStudioSocket', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    MockWebSocket.instances = []
    vi.stubGlobal('WebSocket', MockWebSocket)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('normalizes recognition events and responds to ping', () => {
    const { result, rerender } = renderHook(() => useStudioSocket('ws://studio'))
    const socket = MockWebSocket.instances[0]

    act(() => socket.onopen?.())
    act(() => socket.onmessage?.({ data: JSON.stringify({ type: 'ping' }) }))
    act(() =>
      socket.onmessage?.({
        data: JSON.stringify({
          type: 'recognition',
          subject_id: 'person-2',
          label: 'Hands up',
          confidence: 0.82,
          reason: 'recognized',
        }),
      }),
    )
    rerender()

    expect(result.current.connected).toBe(true)
    expect(result.current.recognition['person-2']).toEqual({
      label: 'Hands up',
      confidence: 0.82,
      reason: 'recognized',
    })
    expect(socket.sent).toEqual([JSON.stringify({ type: 'pong' })])
    expect(MockWebSocket.instances).toHaveLength(1)
  })

  it('reconnects with exponential delay capped at five seconds', () => {
    renderHook(() => useStudioSocket('ws://studio'))

    for (const delay of [500, 1000, 2000, 4000, 5000, 5000]) {
      const socket = MockWebSocket.instances[MockWebSocket.instances.length - 1]
      act(() => socket.onclose?.())
      expect(vi.getTimerCount()).toBe(1)
      act(() => vi.advanceTimersByTime(delay))
    }

    expect(MockWebSocket.instances).toHaveLength(7)
  })
})
