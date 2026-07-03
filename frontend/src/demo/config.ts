// Endpoint configuration for the Director demo.
//
// Robot endpoints (ROBOT_BASE / ROBOT_STREAM / FEATURES_BASE) are NOT here —
// they depend on the runtime sim/hardware toggle, see robotConfig.ts. This file
// only holds the always-on-the-Mac services and demo tuning knobs.

const env = import.meta.env as Record<string, string | undefined>

export const SPEAKER_BASE = env.VITE_SPEAKER_BASE ?? 'http://localhost:5002'
export const ACTION_WS = env.VITE_ACTION_WS ?? 'ws://localhost:8000/ws'

// How many times the CLASSIFY → RECORD loop repeats before the OUTRO.
export const LOOP_COUNT = Number(env.VITE_LOOP_COUNT ?? 3)

// Gesture watch timeout (seconds) for the intro "hands close" trigger.
export const WATCH_TIMEOUT_S = 30
