// Poses a child made in the Pose Designer. Kept in this browser's localStorage
// (no accounts or server storage yet), so they survive a refresh and show up
// as moves in the Dance Game.

const STORAGE_KEY = 'coral.customPoses'
export const MAX_NAME_LENGTH = 24

export interface CustomPose {
  id: string
  name: string
  /** Full-body hardware servo pulses (0-1000), the same format as the Dance Game presets. */
  pulses: Record<string, number>
}

const isPulse = (v: unknown) => typeof v === 'number' && Number.isInteger(v) && v >= 0 && v <= 1000

/** Anything in storage that isn't a well-formed pose is skipped. */
function isCustomPose(v: unknown): v is CustomPose {
  if (!v || typeof v !== 'object') return false
  const p = v as Record<string, unknown>
  return (
    typeof p.id === 'string' &&
    typeof p.name === 'string' &&
    !!p.pulses &&
    typeof p.pulses === 'object' &&
    Object.values(p.pulses as object).every(isPulse)
  )
}

export function loadCustomPoses(): CustomPose[] {
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]')
    return Array.isArray(raw) ? raw.filter(isCustomPose) : []
  } catch {
    return []
  }
}

/** Save a new pose and return it. */
export function saveCustomPose(name: string, pulses: Record<string, number>): CustomPose {
  const pose: CustomPose = {
    id: `custom-${Date.now().toString(36)}`,
    name: name.trim().slice(0, MAX_NAME_LENGTH),
    pulses,
  }
  localStorage.setItem(STORAGE_KEY, JSON.stringify([...loadCustomPoses(), pose]))
  return pose
}
