// Service endpoints. Defaults match ./run.sh; override with VITE_* variables
// at build time (see README).

const env = import.meta.env as Record<string, string | undefined>

/** Main backend (FastAPI on :8000): motion, poses, intent, TTS. */
export const SERVER_BASE = env.VITE_SERVER_BASE ?? 'http://localhost:8000'
/** Chat / audio / command WebSocket on the main backend. */
export const ACTION_WS = env.VITE_ACTION_WS ?? 'ws://localhost:8000/ws'
/** Binary geom-pose stream that drives the in-browser MuJoCo viewer. */
export const SIM_WS = env.VITE_SIM_WS ?? 'ws://localhost:8000/ws/sim'

/** Vision server (:8001): camera stream, pose landmarks, retargeting. */
export const VISION_BASE = env.VITE_VISION_BASE ?? 'http://localhost:8001'
export const VISION_POSE_WS = VISION_BASE.replace(/^http/, 'ws') + '/ws/pose'

/** Pi servo server on the physical robot (Pose Tester only). */
const ROBOT_HOST = env.VITE_ROBOT_HOST ?? '192.168.8.219'
export const PI_BASE = `http://${ROBOT_HOST}:9000`
