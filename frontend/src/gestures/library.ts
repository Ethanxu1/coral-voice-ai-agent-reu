// The gesture library: every gesture recorded in Gesture Studio.
//
// Each gesture is stored two ways:
//   - `pose`: the person's arms as the camera saw them (normalized, see
//     pose/poseSimilarity.ts). Drawn as the stick figure, and usable as a
//     reference pose for camera detection.
//   - `robotPulses`: how CORAL performs it, as hardware servo pulses for the 8
//     arm joints. Starts as the pose the robot reached while copying the person
//     (`recordedPulses`) and can be fine-tuned in the library.
//
// Fine-tuning only changes `robotPulses`, never `pose`: the robot has different
// proportions than a person, so its version of a move is allowed to differ.
//
// Kept in this browser's localStorage, and shared between people as a JSON file
// (exportJson / importJson).

import { useSyncExternalStore } from 'react'
import type { JointName, PoseVector } from '../pose/poseSimilarity'
import { ARM_JOINT_IDS } from './armJoints'

export interface Gesture {
  id: string
  name: string
  pose: PoseVector
  robotPulses: Record<string, number>
  /** robotPulses as first recorded, so fine-tuning can be undone. */
  recordedPulses: Record<string, number>
  createdAt: string
  updatedAt: string
}

export const FILE_FORMAT = 'coral-gestures'
export const FILE_VERSION = 1

export interface GestureFile {
  format: typeof FILE_FORMAT
  version: number
  exportedAt: string
  gestures: Gesture[]
}

const STORAGE_KEY = 'coral.gestureLibrary.v1'

function load(): Gesture[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.map(parseGesture).filter((g): g is Gesture => g !== null) : []
  } catch {
    return []
  }
}

// Filled from localStorage at the bottom of this file, once the parsers below are defined.
let gestures: Gesture[] = []
const listeners = new Set<() => void>()

function commit(next: Gesture[]): void {
  gestures = next
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
  } catch (e) {
    console.warn('saving gesture library failed', e)
  }
  listeners.forEach((l) => l())
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  // Another tab changed the library.
  const onStorage = (e: StorageEvent) => {
    if (e.key === STORAGE_KEY) {
      gestures = load()
      listener()
    }
  }
  window.addEventListener('storage', onStorage)
  return () => {
    listeners.delete(listener)
    window.removeEventListener('storage', onStorage)
  }
}

/** All gestures, newest first. Re-renders when the library changes. */
export function useGestures(): Gesture[] {
  return useSyncExternalStore(subscribe, () => gestures)
}

export function getGestures(): Gesture[] {
  return gestures
}

function newId(): string {
  return crypto.randomUUID?.() ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

/** A name not used by any other gesture: "Wave", "Wave (2)", ... */
export function uniqueName(name: string, exceptId?: string): string {
  return uniqueNameIn(gestures, name, exceptId)
}

function uniqueNameIn(list: Gesture[], name: string, exceptId?: string): string {
  const taken = new Set(list.filter((g) => g.id !== exceptId).map((g) => g.name.toLowerCase()))
  if (!taken.has(name.toLowerCase())) return name
  for (let n = 2; ; n++) {
    const candidate = `${name} (${n})`
    if (!taken.has(candidate.toLowerCase())) return candidate
  }
}

/** Default name for the next recording: "Gesture 1", "Gesture 2", ... */
export function nextDefaultName(): string {
  return uniqueName(`Gesture ${gestures.length + 1}`)
}

export function addGesture(name: string, pose: PoseVector, robotPulses: Record<string, number>): Gesture {
  const now = new Date().toISOString()
  const gesture: Gesture = {
    id: newId(),
    name: uniqueName(name.trim() || nextDefaultName()),
    pose,
    robotPulses: { ...robotPulses },
    recordedPulses: { ...robotPulses },
    createdAt: now,
    updatedAt: now,
  }
  commit([gesture, ...gestures])
  return gesture
}

export function updateGesture(id: string, changes: Partial<Pick<Gesture, 'name' | 'robotPulses'>>): void {
  commit(
    gestures.map((g) => {
      if (g.id !== id) return g
      const name = changes.name !== undefined ? uniqueName(changes.name.trim() || g.name, id) : g.name
      return { ...g, ...changes, name, updatedAt: new Date().toISOString() }
    }),
  )
}

export function deleteGesture(id: string): void {
  commit(gestures.filter((g) => g.id !== id))
}

// ── JSON file ────────────────────────────────────────────────────────────────

export function exportJson(list: Gesture[] = gestures): string {
  const file: GestureFile = {
    format: FILE_FORMAT,
    version: FILE_VERSION,
    exportedAt: new Date().toISOString(),
    gestures: list,
  }
  return JSON.stringify(file, null, 2)
}

/** Save the library (or some of it) as a .json file. */
export function downloadJson(list: Gesture[] = gestures, filename = 'coral-gestures.json'): void {
  const blob = new Blob([exportJson(list)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

const POSE_JOINTS: JointName[] = ['leftElbow', 'rightElbow', 'leftWrist', 'rightWrist']

const isPoint = (p: unknown): p is [number, number] =>
  Array.isArray(p) && p.length === 2 && p.every((v) => typeof v === 'number' && Number.isFinite(v))

function parsePulses(raw: unknown): Record<string, number> | null {
  if (!raw || typeof raw !== 'object') return null
  const out: Record<string, number> = {}
  for (const joint of ARM_JOINT_IDS) {
    const v = (raw as Record<string, unknown>)[joint]
    if (typeof v !== 'number' || !Number.isFinite(v)) return null
    out[joint] = Math.round(Math.min(1000, Math.max(0, v)))
  }
  return out
}

/** A gesture from untrusted JSON, or null if it isn't one. */
function parseGesture(raw: unknown): Gesture | null {
  if (!raw || typeof raw !== 'object') return null
  const r = raw as Record<string, unknown>
  if (typeof r.name !== 'string' || !r.pose || typeof r.pose !== 'object') return null
  const pose: PoseVector = {}
  for (const j of POSE_JOINTS) {
    const p = (r.pose as Record<string, unknown>)[j]
    if (!isPoint(p)) return null
    pose[j] = [p[0], p[1]]
  }
  const robotPulses = parsePulses(r.robotPulses)
  if (!robotPulses) return null
  const now = new Date().toISOString()
  return {
    id: typeof r.id === 'string' && r.id ? r.id : newId(),
    name: r.name.trim().slice(0, 60) || 'Imported gesture',
    pose,
    robotPulses,
    recordedPulses: parsePulses(r.recordedPulses) ?? { ...robotPulses },
    createdAt: typeof r.createdAt === 'string' ? r.createdAt : now,
    updatedAt: typeof r.updatedAt === 'string' ? r.updatedAt : now,
  }
}

export interface ImportResult {
  added: number
  updated: number
  skipped: number
  invalid: number
}

/**
 * Merge a gesture JSON file into the library. A gesture whose id is already in
 * the library replaces it only if the file's copy was edited more recently. A
 * new gesture whose name is taken gets a "(2)" suffix. Throws if the file isn't
 * a gesture file at all.
 */
export function importJson(text: string): ImportResult {
  let data: unknown
  try {
    data = JSON.parse(text)
  } catch {
    throw new Error("That file isn't valid JSON.")
  }
  // Accept a full export file or a bare array of gestures.
  const list = Array.isArray(data)
    ? data
    : data && typeof data === 'object' && Array.isArray((data as GestureFile).gestures)
      ? (data as GestureFile).gestures
      : null
  if (!list) throw new Error("That file doesn't contain any gestures.")

  const result: ImportResult = { added: 0, updated: 0, skipped: 0, invalid: 0 }
  let next = [...gestures]
  for (const raw of list) {
    const g = parseGesture(raw)
    if (!g) {
      result.invalid++
      continue
    }
    const at = next.findIndex((x) => x.id === g.id)
    if (at >= 0) {
      if (g.updatedAt > next[at].updatedAt) {
        next[at] = { ...g, name: uniqueNameIn(next, g.name, g.id) }
        result.updated++
      } else {
        result.skipped++
      }
    } else {
      next = [{ ...g, name: uniqueNameIn(next, g.name) }, ...next]
      result.added++
    }
  }
  if (result.invalid === list.length && list.length > 0) throw new Error('None of the gestures in that file could be read.')
  commit(next)
  return result
}

gestures = load()
