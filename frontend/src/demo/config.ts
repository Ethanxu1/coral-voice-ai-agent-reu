// Endpoint configuration for the Director demo.
//
// Defaults assume everything is reachable from the Mac running the frontend:
//   - speaker server + audio/LLM server are local
//   - the Pi (robot_server + vision stream) is reachable at VITE_ROBOT_HOST
// Override per-machine with a frontend/.env file (VITE_ROBOT_HOST=192.168.8.219).

const env = import.meta.env as Record<string, string | undefined>

const ROBOT_HOST = env.VITE_ROBOT_HOST ?? 'localhost'

export const SPEAKER_BASE = env.VITE_SPEAKER_BASE ?? 'http://localhost:5002'
export const ROBOT_BASE = env.VITE_ROBOT_BASE ?? `http://${ROBOT_HOST}:9000`
export const ROBOT_STREAM = env.VITE_ROBOT_STREAM ?? `http://${ROBOT_HOST}:9001`
export const ACTION_WS = env.VITE_ACTION_WS ?? 'ws://localhost:8000/ws'

// How many times the CLASSIFY → RECORD loop repeats before the OUTRO.
export const LOOP_COUNT = Number(env.VITE_LOOP_COUNT ?? 3)

// Gesture watch timeout (seconds) for the intro "hands close" trigger.
export const WATCH_TIMEOUT_S = 30
