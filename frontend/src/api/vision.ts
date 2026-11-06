// Vision server (:8001) calls: pose retargeting and subject selection.

import { VISION_BASE, VISION_POSE_WS } from '../config'
import { postBestEffort } from './http'
import type { ServoCommand } from './robot'

/** Result of retargeting the user's pose (landmarks → robot joints). */
export interface MapFeaturesResult {
  /** False when the hips aren't visible: no arm retargeting, caller should retake. */
  poseDetected: boolean
  /** Human-readable reason to show when poseDetected is false. */
  detail: string | null
  commands: ServoCommand[]
  imageB64: string | null
}

// Retarget the user's current pose to robot servo commands. The caller executes
// the returned commands via move(). Also returns the frame the pose was read
// from, for the UI.
export async function mapFeatures(): Promise<MapFeaturesResult> {
  const res = await fetch(`${VISION_BASE}/map-features`, { method: 'POST' })
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(`map-features failed: ${res.status} ${body?.detail ?? ''}`.trim())
  }
  const data = await res.json()
  return {
    poseDetected: data.pose_detected !== false,
    detail: data.detail ?? null,
    commands: Array.isArray(data.commands) ? data.commands : [],
    imageB64: data.image_b64 ?? null,
  }
}

// ── Subject selection (multi-person re-ID lock) ──────────────────────────────
export type SubjectSelectionState = 'idle' | 'selecting' | 'selected' | 'searching'

interface SubjectSelectionUpdate {
  state: SubjectSelectionState
  selectedSubjectId: string | null
  subjectsCount: number
  // Max hold_progress (0-1) across all current candidates — drives the modal's
  // "raise-and-hold" progress bar.
  holdProgress: number
}

export async function startSubjectSelection(): Promise<void> {
  await fetch(`${VISION_BASE}/subject-selection/start`, { method: 'POST' })
}

export async function resetSubjectSelection(): Promise<void> {
  await fetch(`${VISION_BASE}/subject-selection/reset`, { method: 'POST' })
}

// Teardown: returns the vision server to single-person mode, even on page unload.
export function stopSubjectSelection(): Promise<void> {
  return postBestEffort(`${VISION_BASE}/subject-selection/stop`)
}

// Subscribe to pose updates from the vision server and surface only the
// subject-selection fields. Auto-reconnects on drop until the returned cleanup
// is called.
export function subscribeSubjectSelection(
  onUpdate: (u: SubjectSelectionUpdate) => void,
): () => void {
  let ws: WebSocket | null = null
  let retry: ReturnType<typeof setTimeout> | null = null
  let closed = false

  const open = () => {
    if (closed) return
    ws = new WebSocket(VISION_POSE_WS)
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.type !== 'pose_update') return
        const subjects = Array.isArray(data.subjects) ? data.subjects : []
        let hold = 0
        for (const s of subjects) {
          const p = typeof s?.hold_progress === 'number' ? s.hold_progress : 0
          if (p > hold) hold = p
        }
        onUpdate({
          state: (data.selection_state ?? 'idle') as SubjectSelectionState,
          selectedSubjectId: data.selected_subject_id ?? null,
          subjectsCount: subjects.length,
          holdProgress: hold,
        })
      } catch {
        /* ignore malformed frames */
      }
    }
    ws.onclose = () => {
      if (closed) return
      retry = setTimeout(open, 1500)
    }
    ws.onerror = () => {
      try { ws?.close() } catch { /* ignore */ }
    }
  }

  open()
  return () => {
    closed = true
    if (retry) clearTimeout(retry)
    try { ws?.close() } catch { /* ignore */ }
  }
}
