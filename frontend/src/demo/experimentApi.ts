// Client for the joint-angle accuracy experiment endpoints (server.py
// /experiment/*). The capture itself happens server-side so it can reuse the
// demo's own /map-features -> /move path, safety layer included — the frontend
// sequences trials and collects the protractor readings.

import { getRobotBase, getRobotConfig } from './robotConfig'

export type AngleSet = Record<string, Record<string, number>>

export interface TrialSafety {
  fall_blocked?: boolean
  collision_clamped?: boolean
  safe_fraction?: number
}

export interface Trial {
  order_index: number
  pose: string
  pose_label: string
  cue: string
  rep: number
  captured: boolean
  recorded: boolean
  photo: string
  timestamp: string
  est: AngleSet
  mapped: AngleSet
  applied: AngleSet
  clamped: string[][]
  robot: AngleSet
  safety: TrialSafety
  notes: string
  nominal: Record<string, number>
}

export interface SessionState {
  session_id: string
  meta: Record<string, unknown>
  trials: Trial[]
  next_unrecorded: number | null
  recorded_count: number
  total: number
  measurements: { key: string; label: string }[]
  arms: { arm: string; human_side: string }[]
  csv_path: string
}

export interface CaptureResult {
  captured: boolean
  detail?: string
  blocked?: boolean
  trial?: Trial
  safety?: TrialSafety
  image_b64?: string
  leg_mode?: string
}

export interface SessionSummary {
  session_id: string
  started: string
  demonstrator: string
  recorded_count: number
  total: number
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${getRobotBase()}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    // FastAPI puts the real reason in `detail`; surfacing it beats a bare status.
    const body = await res.json().catch(() => null)
    throw new Error(`${res.status} ${body?.detail ?? path}`.trim())
  }
  return res.json()
}

export function listSessions(): Promise<{ sessions: SessionSummary[] }> {
  return req('/experiment/sessions')
}

export function createSession(meta: {
  seed: number
  demonstrator: string
  camera_height_cm: string
  camera_distance_cm: string
  lighting: string
}): Promise<SessionState> {
  return req('/experiment/session', { method: 'POST', body: JSON.stringify(meta) })
}

export function getSession(sessionId: string): Promise<SessionState> {
  return req(`/experiment/session/${sessionId}`)
}

export function captureTrial(
  sessionId: string,
  orderIndex: number,
  dispatch: boolean,
): Promise<CaptureResult> {
  // Same leg mode and sim/hardware target the demo would use for this capture.
  const { legMode, simOnly } = getRobotConfig()
  return req('/experiment/capture', {
    method: 'POST',
    body: JSON.stringify({
      session_id: sessionId,
      order_index: orderIndex,
      leg_mode: legMode,
      sim_only: simOnly,
      dispatch,
    }),
  })
}

export function recordTrial(
  sessionId: string,
  orderIndex: number,
  readings: AngleSet,
  notes: string,
): Promise<SessionState> {
  return req('/experiment/record', {
    method: 'POST',
    body: JSON.stringify({
      session_id: sessionId,
      order_index: orderIndex,
      readings,
      notes,
    }),
  })
}
