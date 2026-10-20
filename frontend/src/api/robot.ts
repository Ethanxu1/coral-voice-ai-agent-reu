// Main backend (:8000) REST calls: motion, saved poses, intent classification.

import { PI_BASE, SERVER_BASE } from '../config'
import { beginHardwareDispatch } from '../demo/hardwareDispatchStatus'
import { post, postBestEffort, postJSON } from './http'

/** One servo target: Hiwonder id + pulse (0–1000) + move time. */
export interface ServoCommand {
  servo_id: number
  position: number
  duration_ms: number
}

// Safety-check outcome attached to /move responses. `fallBlocked` means the
// dynamics shadow-check saw the robot topple, so the server executed 0% of
// the move; `collisionClamped` means the kinematic checker pulled the motion
// back to `safeFraction` of the commanded target.
export interface MoveSafety {
  fallBlocked: boolean
  collisionClamped: boolean
  safeFraction: number
  badPairs: string[]
}

const SAFE_MOVE: MoveSafety = {
  fallBlocked: false,
  collisionClamped: false,
  safeFraction: 1,
  badPairs: [],
}

// Parse the server's snake_case safety report. /move and the /ws chat_response
// (aggregate_safety in services/motion.py) emit the same shape. Returns null
// when the field is absent — for chat that means the turn moved nothing.
export function parseSafety(raw: unknown): MoveSafety | null {
  if (!raw || typeof raw !== 'object') return null
  const s = raw as Record<string, unknown>
  return {
    fallBlocked: s.fall_blocked === true,
    collisionClamped: s.collision_clamped === true,
    safeFraction: typeof s.safe_fraction === 'number' ? s.safe_fraction : 1,
    badPairs: Array.isArray(s.bad_pairs) ? (s.bad_pairs as string[]) : [],
  }
}

// Drive the robot/sim with raw servo commands (from mapFeatures). Returns the
// server's safety verdict so callers can report a blocked move.
export async function move(
  commands: ServoCommand[],
): Promise<{ executed: boolean; safety: MoveSafety }> {
  if (commands.length === 0) return { executed: false, safety: SAFE_MOVE }
  const data = await postJSON<{ status?: string; safety?: unknown } | null>(
    `${SERVER_BASE}/move`,
    { moves: commands },
    'move',
  )
  return {
    executed: data?.status !== 'blocked',
    safety: parseSafety(data?.safety) ?? SAFE_MOVE,
  }
}

// Snap the sim (and, in robot mode, animate the hardware) back to the stand pose.
export async function resetPose(): Promise<void> {
  await post(`${SERVER_BASE}/reset`, 'reset')
}

export interface SetPoseResult {
  /** 'blocked' when the fall check refused the pose (nothing moved). */
  status: 'done' | 'blocked'
  applied: string[]
  skipped: string[]
  safety: MoveSafety
}

// Apply a raw {joint: hardware_pulse} pose to the sim (never the robot). Pulses
// are the hardware units authored in motions.py; the server converts them to
// sim radians. `durationMs` > 0 glides there over that time (0 = instant).
// `skipCollisionCheck` bypasses the collision/fall gate (joint limits still
// clamp); `checkFall: false` skips only the fall check (test pages, which pin
// the sim upright instead).
export async function setPose(
  pulses: Record<string, number>,
  {
    durationMs = 0,
    skipCollisionCheck = false,
    checkFall = true,
  }: { durationMs?: number; skipCollisionCheck?: boolean; checkFall?: boolean } = {},
): Promise<SetPoseResult> {
  const data = await postJSON<{
    status: 'done' | 'blocked'
    applied?: string[]
    skipped?: string[]
    safety?: unknown
  }>(
    `${SERVER_BASE}/set-pose`,
    { pulses, duration_ms: durationMs, skip_collision_check: skipCollisionCheck, check_fall: checkFall },
    'set-pose',
  )
  return {
    status: data.status,
    applied: data.applied ?? [],
    skipped: data.skipped ?? [],
    safety: parseSafety(data.safety) ?? SAFE_MOVE,
  }
}

/** joint name → Hiwonder servo id (mirrors the backend's SERVO_ID_MAP). */
const SERVO_ID: Record<string, number> = {
  l_ank_roll: 1, r_ank_roll: 2,
  l_ank_pitch: 3, r_ank_pitch: 4,
  l_knee: 5, r_knee: 6,
  l_hip_pitch: 7, r_hip_pitch: 8,
  l_hip_roll: 9, r_hip_roll: 10,
  l_hip_yaw: 11, r_hip_yaw: 12,
  l_sho_pitch: 13, r_sho_pitch: 14,
  l_sho_roll: 15, r_sho_roll: 16,
  l_el_pitch: 17, r_el_pitch: 18,
  l_el_yaw: 19, r_el_yaw: 20,
  l_gripper: 21, r_gripper: 22,
  head_pan: 23, head_tilt: 24,
}

// Play a raw {joint: hardware_pulse} pose on the physical robot via the Pi's
// /move endpoint (testing tool). Pulses go to the hardware as-is (the Pi clamps
// to each servo's safe range); the response returns after the motion finishes.
export async function movePulses(
  pulses: Record<string, number>,
  durationMs: number,
): Promise<{ count: number }> {
  const commands: ServoCommand[] = Object.entries(pulses)
    .filter(([name]) => SERVO_ID[name] !== undefined)
    .map(([name, position]) => ({ servo_id: SERVO_ID[name], position, duration_ms: durationMs }))
  const data = await postJSON<{ count?: number } | null>(`${PI_BASE}/move`, commands, 'robot move')
  return { count: data?.count ?? commands.length }
}

// Hold the simulated robot's body upright so it can't tip or fall (sim only).
export function setSimUpright(enabled: boolean): Promise<void> {
  return postBestEffort(`${SERVER_BASE}/sim/upright`, { enabled })
}

// Rock-Paper-Scissors only follows the head and arms, so while it is open the
// backend's follow mode doesn't need the hips in view.
export function setHiplessFollow(enabled: boolean): Promise<void> {
  return postBestEffort(`${SERVER_BASE}/follow/hipless-arms`, { enabled })
}

// ── Saved poses ───────────────────────────────────────────────────────────────
export async function listPoses(): Promise<string[]> {
  const res = await fetch(`${SERVER_BASE}/poses`)
  if (!res.ok) return []
  const data = await res.json()
  return data.poses ?? []
}

// Best-effort: a failed save must not stop the demo.
export async function saveCurrentPose(name: string): Promise<void> {
  const endDispatch = beginHardwareDispatch()
  try {
    await fetch(`${SERVER_BASE}/poses/save-current`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    })
  } finally {
    endDispatch()
  }
}

// Strike a saved pose directly by name (no LLM). sim_only is intentionally
// omitted — demonstrating a saved pose always reaches hardware once connected.
export async function playPose(name: string, durationMs = 1000): Promise<void> {
  const endDispatch = beginHardwareDispatch()
  try {
    await postJSON(`${SERVER_BASE}/poses/play`, { name, duration_ms: durationMs }, 'play pose')
  } finally {
    endDispatch()
  }
}

// Filter a child's free-form naming answer down to just the intended name
// (e.g. "let's name it Buddy" -> "Buddy") via a small backend LLM call.
export async function extractName(text: string): Promise<string> {
  const data = await postJSON<{ name: string }>(
    `${SERVER_BASE}/poses/extract-name`,
    { text },
    'extract name',
  )
  return data.name
}

// ── Intent classification ─────────────────────────────────────────────────────
// `classifier` is 'regex' or 'llm', and `reason` explains why that classifier
// was chosen. `name` is set for the `naming` intent when the child suggests one.
export type IntentResult =
  | { type: 'immediate'; intent: string; name?: string; classifier: 'regex' | 'llm'; reason: string }
  | { type: 'clarification'; question: string; classifier: 'regex' | 'llm'; reason: string }
  | { type: 'conversation'; text: string; classifier: 'regex' | 'llm'; reason: string }
  | { type: 'motion'; description: string; classifier: 'regex' | 'llm'; reason: string }

export interface ChatMsg {
  role: 'agent' | 'child' | 'system'
  text: string
}

function msgsToHistory(msgs: ChatMsg[]): { role: 'user' | 'assistant'; content: string }[] {
  const out: { role: 'user' | 'assistant'; content: string }[] = []
  for (const m of msgs) {
    if (m.role === 'child') out.push({ role: 'user', content: m.text })
    else if (m.role === 'agent') out.push({ role: 'assistant', content: m.text })
    // 'system' messages (e.g. "Starting countdown…") are UI-only, skip them
  }
  return out
}

export async function classifyIntent(
  text: string,
  followActive: boolean,
  msgs?: ChatMsg[],
  sessionId?: string,
): Promise<IntentResult> {
  const history = msgs ? msgsToHistory(msgs) : undefined
  const res = await fetch(`${SERVER_BASE}/classify-intent`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, follow_active: followActive, history, session_id: sessionId }),
  })
  // If the classifier can't answer, fall back to conversation so the agent
  // chats/asks instead of showing the approve/reject modal.
  if (!res.ok) return { type: 'conversation', text, classifier: 'llm', reason: 'classifier request failed' }
  const data = await res.json()
  if (data.type === 'immediate' && data.intent) return data as IntentResult
  if (data.type === 'clarification' && data.question) return data as IntentResult
  if (data.type === 'conversation' && data.text) return data as IntentResult
  if (data.type === 'motion' && data.description) return data as IntentResult
  return { type: 'conversation', text, classifier: 'llm', reason: 'unrecognized classifier response' }
}

/** Example phrases for the in-demo command palette, grouped by intent. */
export interface IntentExamples {
  motion: string[]
  immediate: string[]
  conversation: string[]
}

export async function fetchIntentExamples(): Promise<IntentExamples> {
  const res = await fetch(`${SERVER_BASE}/intent/examples`)
  if (!res.ok) return { motion: [], immediate: [], conversation: [] }
  const data = await res.json().catch(() => ({}))
  return {
    motion: Array.isArray(data.motion) ? data.motion : [],
    immediate: Array.isArray(data.immediate) ? data.immediate : [],
    conversation: Array.isArray(data.conversation) ? data.conversation : [],
  }
}
