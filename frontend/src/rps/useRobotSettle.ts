import { useEffect, useRef } from 'react'
import { getJointPulses } from '../demo/api'
import { ROBOT_REST_PULSES } from './gestures'

/**
 * The robot follows in gentle mode, so it lags the person. A recording should
 * only be saved once the robot has caught up: over the last SETTLE_MS (polled
 * every POLL_MS) no arm joint ranged more than SETTLE_PULSES.
 *
 * The robot never stands perfectly still while following, because landmark
 * noise reaches it: a held pose still wobbles 20-50 pulses. Catching up is far
 * bigger (about 380 pulses a second), so the limit sits between the two. The
 * pose returned is the average over that window, which smooths the wobble.
 */
const POLL_MS = 200
const SETTLE_PULSES = 60
const SETTLE_MS = 800

const ARM_JOINTS = Object.keys(ROBOT_REST_PULSES)

type Poll = { t: number; pulses: Record<string, number> }

/** Average arm pose over the last SETTLE_MS, or null if still moving or too few polls to tell. */
function settledPose(polls: Poll[], now: number): Record<string, number> | null {
  const recent = polls.filter((p) => now - p.t <= SETTLE_MS)
  if (recent.length === 0 || now - recent[0].t < SETTLE_MS - POLL_MS) return null
  const average: Record<string, number> = {}
  for (const j of ARM_JOINTS) {
    const values = recent.map((p) => p.pulses[j]).filter((v) => v !== undefined)
    if (values.length === 0) continue
    if (Math.max(...values) - Math.min(...values) > SETTLE_PULSES) return null
    average[j] = Math.round(values.reduce((a, b) => a + b, 0) / values.length)
  }
  return average
}

/**
 * While `active`, polls the robot's arm pose. Returns a function giving the
 * robot's settled arm pose (averaged over the last SETTLE_MS) right now, or
 * null while it is still moving.
 */
export function useRobotSettle(active: boolean): () => Record<string, number> | null {
  const pollsRef = useRef<Poll[]>([])

  useEffect(() => {
    pollsRef.current = []
    if (!active) return
    let stopped = false
    const poll = async () => {
      try {
        const all = await getJointPulses()
        if (stopped) return
        const now = Date.now()
        // Keep a little more than the settle window.
        pollsRef.current = [...pollsRef.current.filter((p) => now - p.t <= SETTLE_MS + POLL_MS), { t: now, pulses: all }]
      } catch {
        /* try again next tick */
      }
    }
    poll()
    const timer = setInterval(poll, POLL_MS)
    return () => {
      stopped = true
      clearInterval(timer)
    }
  }, [active])

  return () => settledPose(pollsRef.current, Date.now())
}
