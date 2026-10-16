import { afterEach, describe, expect, it, vi } from 'vitest'

import { studioApi } from './api'

function jsonResponse(body: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
    ...init,
  })
}

describe('studioApi live pose mirroring', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('mirrors only upper-body arm joints at the fixed RPS transition rate', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({
        pose_detected: true,
        targets: { l_sho_pitch: 0.2, l_knee: 0.2, head_pan: 0.1 },
        commands: [
          { servo_id: 13, position: 600, duration_ms: 1000 },
          { servo_id: 5, position: 550, duration_ms: 1000 },
          { servo_id: 23, position: 520, duration_ms: 1000 },
        ],
        body_landmarks: [],
      }))
      .mockResolvedValueOnce(jsonResponse({
        status: 'done',
        targets: { l_knee: 0.1 },
        safety: {
          fall_blocked: false,
          collision_clamped: true,
          safe_fraction: 0.5,
          bad_pairs: [],
        },
      }))
    vi.stubGlobal('fetch', fetchMock)
    const abort = new AbortController()

    const result = await studioApi.mirrorRetargetedPose(abort.signal)

    expect(fetchMock.mock.calls[0][0]).toBe(
      'http://localhost:8001/map-features?upper_body_only=true',
    )
    expect(fetchMock.mock.calls[0][1]).toEqual(expect.objectContaining({ signal: abort.signal }))
    expect(JSON.parse(String(fetchMock.mock.calls[1][1].body))).toEqual(expect.objectContaining({
      sim_only: true,
      stabilized_preview: true,
      moves: [{ servo_id: 13, position: 600, duration_ms: 400 }],
    }))
    expect(result.targets).toEqual({ l_knee: 0.1 })
  })

  it('rejects a successful HTTP response with an invalid mirror contract', async () => {
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce(jsonResponse({
        pose_detected: true,
        targets: {},
        commands: [{ servo_id: 13, position: 600, duration_ms: 120 }],
        body_landmarks: [],
      }))
      .mockResolvedValueOnce(jsonResponse({
        status: 'error',
        detail: 'simulation server is not initialized',
      })))

    await expect(studioApi.mirrorRetargetedPose()).rejects.toThrow(
      'simulation server is not initialized',
    )
  })

  it('requests a simulator-only reset', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ status: 'done' }))
    vi.stubGlobal('fetch', fetchMock)

    await studioApi.resetSimulator()

    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/reset?sim_only=true',
      { method: 'POST' },
    )
  })

  it('rejects a reset response when the simulator is unavailable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({
      status: 'error',
      detail: 'simulator not initialized',
    })))

    await expect(studioApi.resetSimulator()).rejects.toThrow('simulator not initialized')
  })

  it('explains when a saved pose cannot be deleted because it is in use', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({
      detail: { dependents: ['sequence-1'] },
    }, { status: 409 })))

    await expect(studioApi.deleteRobotPose('pose-1')).rejects.toThrow(
      'This pose is used by 1 saved sequence or rule. Remove that reference first.',
    )
  })
})
