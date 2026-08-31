// Endpoint configuration for the Director demo.
//
// Robot endpoints (ROBOT_BASE / ROBOT_STREAM / FEATURES_BASE) are NOT here —
// they depend on the runtime sim/hardware toggle, see robotConfig.ts. This file
// only holds the always-on-the-Mac services and demo tuning knobs.

const env = import.meta.env as Record<string, string | undefined>
const runtime = (typeof window !== 'undefined' && (window as any).__CORAL_RUNTIME__) || {}

export const SPEAKER_BASE = runtime.SPEAKER_BASE ?? env.VITE_SPEAKER_BASE ?? 'http://localhost:5002'
export const ACTION_WS = runtime.ACTION_WS ?? env.VITE_ACTION_WS ?? 'ws://localhost:8000/ws'
// Binary geom-pose stream that drives the in-browser MuJoCo viewer (RobotViewer).
export const SIM_WS = runtime.SIM_WS ?? env.VITE_SIM_WS ?? 'ws://localhost:8000/ws/sim'

// How many times the CLASSIFY → RECORD loop repeats before the OUTRO.
export const LOOP_COUNT = Number(env.VITE_LOOP_COUNT ?? 1)

// Gesture watch timeout (seconds) for the intro "hands close" trigger.
export const WATCH_TIMEOUT_S = 30

// If interpreting the child's spoken/typed direction takes longer than this,
// give up on that attempt and re-ask for directions (re-speak the RECORD prompt).
export const RECORD_PROCESS_TIMEOUT_MS = 7000
