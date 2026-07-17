// Runtime sim/hardware toggle for the robot endpoints (/motion, /move,
// /map-features, /video_feed). Previously this was a build-time .env edit
// (VITE_ROBOT_BASE / VITE_ROBOT_HOST) requiring a dev-server restart to switch;
// this store lets the UI flip it live, persisted in localStorage.
//
// Not a React context — api.ts calls these getters from plain async functions,
// not components, so a module-level store + subscriber list is simpler than
// wiring context through every call site. Components that need to re-render on
// change (e.g. the live camera feed) use the useRobotConfig() hook below.

import { useSyncExternalStore } from 'react'

export type RobotMode = 'sim' | 'hardware'

/** How /map-features drives the legs. Arms always use live retargeting.
 *  - retarget: live pelvis-frame hip pitch/roll + knee bend (default)
 *  - legacy:   old atan2 mapping (hip_yaw ← forward/back swing)
 *  - classify: MobileNetV3 → snap legs to the matching canned pose
 *  - buckets:  classify knee/ankle/hip-pitch depth (both legs together) and
 *              hip yaw (each leg independently) into discrete low/stand/high
 *              and in/stand/out stances, then snap to the matching targets */
export type LegMode = 'retarget' | 'legacy' | 'classify' | 'buckets'

export interface RobotConfig {
  mode: RobotMode
  /** Pi hostname/IP used to build robot + stream URLs in hardware mode. */
  piHost: string
  /** Leg-retargeting strategy passed to /map-features. */
  legMode: LegMode
  /** Debug overlay: draw the knee-bend/hip-yaw angle arcs on the live video
   *  feed (Mac vision-server only — see POST /settings/angle-arcs). Off by
   *  default so it doesn't clutter the kid-facing demo pages. */
  showAngleArcs: boolean
}

const STORAGE_KEY = 'coral.robotConfig'
const env = import.meta.env as Record<string, string | undefined>

const DEFAULT_CONFIG: RobotConfig = {
  mode: 'sim',
  piHost: env.VITE_ROBOT_HOST ?? '192.168.8.219',
  legMode: 'retarget',
  showAngleArcs: false,
}

function loadConfig(): RobotConfig {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return { ...DEFAULT_CONFIG, ...JSON.parse(raw) }
  } catch {
    /* ignore malformed storage */
  }
  return DEFAULT_CONFIG
}

let config: RobotConfig = loadConfig()
const listeners = new Set<() => void>()

export function getRobotConfig(): RobotConfig {
  return config
}

export function setRobotConfig(patch: Partial<RobotConfig>): void {
  config = { ...config, ...patch }
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(config))
  } catch {
    /* storage unavailable — config still applies for this session */
  }
  listeners.forEach((fn) => fn())
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

/** React hook: re-renders the component whenever the sim/hardware mode or Pi host changes. */
export function useRobotConfig(): RobotConfig {
  return useSyncExternalStore(subscribe, getRobotConfig)
}

// SIM MODE: everything runs on the Mac — main server :8000, vision server :8001.
// HARDWARE MODE: the Pi's robot_server serves both /motion+/move (:9000) and
// /map-features (:9000, computed from ROS topics), while its camera stream and
// the Mac's own vision-server stream both sit one port up.
export function getRobotBase(): string {
  const { mode, piHost } = config
  if (mode === 'hardware') return `http://${piHost}:9000`
  return env.VITE_ROBOT_BASE ?? 'http://localhost:8000'
}

export function getRobotStream(): string {
  const { mode, piHost } = config
  if (mode === 'hardware') return `http://${piHost}:9001`
  return env.VITE_ROBOT_STREAM ?? 'http://localhost:8001'
}

export function getFeaturesBase(): string {
  const { mode, piHost } = config
  if (mode === 'hardware') return `http://${piHost}:9000`
  return env.VITE_FEATURES_BASE ?? 'http://localhost:8001'
}

// Mode-independent bases, for tools that pick their target explicitly (e.g.
// the Pose Tester's sim/robot/both selector) instead of following the toggle.

/** Mac sim server (:8000), regardless of the sim/hardware toggle. */
export function getSimBase(): string {
  return env.VITE_ROBOT_BASE ?? 'http://localhost:8000'
}

/** Pi robot server (:9000), regardless of the sim/hardware toggle. */
export function getPiBase(): string {
  return `http://${config.piHost}:9000`
}
