// Small module-level store for the few runtime frontend settings that remain.
// Not a React context — api.ts calls getters from plain async functions, and
// only components that need live updates use the hook.

import { useSyncExternalStore } from 'react'

export interface RobotConfig {
  /** Pi hostname/IP used by explicit robot-only tools (PoseTester). */
  piHost: string
}

const STORAGE_KEY = 'coral.robotConfig.v3'
const env = import.meta.env as Record<string, string | undefined>
const runtime = (typeof window !== 'undefined' && (window as any).__CORAL_RUNTIME__) || {}

const DEFAULT_CONFIG: RobotConfig = {
  piHost: env.VITE_ROBOT_HOST ?? runtime.ROBOT_HOST ?? '192.168.8.219',
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

/** React hook: re-renders the component whenever its configuration changes. */
export function useRobotConfig(): RobotConfig {
  return useSyncExternalStore(subscribe, getRobotConfig)
}

/** Main backend API base (sim or hardware mode). */
export function getRobotBase(): string {
  return runtime.ROBOT_BASE ?? env.VITE_ROBOT_BASE ?? 'http://localhost:8000'
}

/** Vision / MJPEG stream base. */
export function getRobotStream(): string {
  return runtime.ROBOT_STREAM ?? env.VITE_ROBOT_STREAM ?? 'http://localhost:8001'
}

/** Vision feature endpoints base. */
export function getFeaturesBase(): string {
  return runtime.FEATURES_BASE ?? env.VITE_FEATURES_BASE ?? 'http://localhost:8001'
}

/** Mac sim server (:8000), regardless of the sim/hardware toggle. */
export function getSimBase(): string {
  return runtime.ROBOT_BASE ?? env.VITE_ROBOT_BASE ?? 'http://localhost:8000'
}

/** Pi robot server (:9000), regardless of the sim/hardware toggle. */
export function getPiBase(): string {
  return `http://${config.piHost}:9000`
}
