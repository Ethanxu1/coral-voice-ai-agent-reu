// Tracks whether a "hardware-eligible" dispatch (pose save / demonstrate) is
// currently in flight, so the UI can show an "Executing on robot…" pill.
//
// Shown regardless of sim/live mode and regardless of whether a physical
// robot is actually connected — the backend no-ops the hardware side in sim
// mode, but the pill still fires so a developer without a robot attached can
// see exactly when a save or demonstrate action would reach hardware. See
// the 2026-08-27 fix (pose save/demonstrate now always target hardware once
// connected, independent of the sim/hardware toggle).
//
// Counter-based (not a plain boolean) so nested/overlapping callers — e.g.
// the exit replay wrapping its whole loop while each individual playPose()
// call also wraps itself — don't clear the pill out from under each other.

import { useSyncExternalStore } from 'react'

let count = 0
const listeners = new Set<() => void>()

function notify(): void {
  listeners.forEach((fn) => fn())
}

/** Marks one hardware-eligible dispatch as in flight. Call the returned
 *  function exactly once when it's done, success or failure (use `finally`). */
export function beginHardwareDispatch(): () => void {
  count += 1
  notify()
  let ended = false
  return () => {
    if (ended) return
    ended = true
    count = Math.max(0, count - 1)
    notify()
  }
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

function getSnapshot(): boolean {
  return count > 0
}

export function useHardwareDispatching(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot)
}
