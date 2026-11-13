// Pose Designer calls on the main backend (:8000): a conversation turn, the
// "save this pose" check, and the ghost preview of a proposed pose. None moves the robot.

import { SERVER_BASE } from '../config'
import { postJSON } from './http'

/**
 * 'wake': just "hey CORAL" (listen for the request next). 'ignore': heard while
 * CORAL was asleep, without "hey CORAL", so not meant for CORAL.
 */
export type DesignAction = 'propose' | 'accept' | 'reject' | 'done' | 'chat' | 'wake' | 'ignore'

/** One control moved, e.g. { label: 'Right arm forward/up', degrees: 10 }. */
export interface DesignChange {
  control: string
  label: string
  degrees: number
}

export interface DesignTurn {
  action: DesignAction
  /** What CORAL says back. */
  reply: string
  /** The proposal (from the current pose), for 'propose'. */
  changes: DesignChange[]
  /** The pose the proposal would give, for 'propose'. */
  proposedPulses: Record<string, number> | null
}

export interface ChatTurn {
  role: 'user' | 'assistant'
  content: string
}

/**
 * Ask CORAL what the child wants done to the pose. `proposal` is the change still
 * waiting for a yes or no, as {control: degrees}; `history` the conversation so far.
 * `needsWakeWord` (heard while CORAL is asleep): only counts with "hey CORAL", else 'ignore'.
 */
export async function designTurn(
  text: string,
  pulses: Record<string, number>,
  proposal: Record<string, number>,
  history: ChatTurn[],
  needsWakeWord: boolean,
): Promise<DesignTurn> {
  const data = await postJSON<{
    action: DesignAction
    reply: string
    changes: DesignChange[]
    proposed_pulses: Record<string, number> | null
  }>(`${SERVER_BASE}/pose-design/turn`, { text, pulses, proposal, history, needs_wake_word: needsWakeWord }, 'pose design turn')
  return { action: data.action, reply: data.reply, changes: data.changes, proposedPulses: data.proposed_pulses }
}

/** Whether the child said to keep the pose CORAL is following them into ("save this pose", "freeze!"). */
export async function isSaveCommand(text: string): Promise<boolean> {
  const data = await postJSON<{ save: boolean }>(`${SERVER_BASE}/pose-design/save-command`, { text }, 'save command')
  return data.save
}

/** Where every robot link would be with these joints set: RobotViewer's `ghost`. */
export async function previewPose(pulses: Record<string, number>): Promise<Float32Array> {
  const data = await postJSON<{ poses: number[] }>(`${SERVER_BASE}/pose-design/preview`, { pulses }, 'pose preview')
  return new Float32Array(data.poses)
}

/** Stick-figure points of a pose, {name: [x, y, z]} in metres: x forward, y the robot's left, z up. */
export type Skeleton = Record<string, [number, number, number]>

/** A stick figure of each pose ({id: pulses}), from the robot's geometry (Dance Game icons). */
export async function poseSkeletons(poses: Record<string, Record<string, number>>): Promise<Record<string, Skeleton>> {
  const data = await postJSON<{ skeletons: Record<string, Skeleton> }>(`${SERVER_BASE}/pose-design/skeletons`, { poses }, 'pose skeletons')
  return data.skeletons
}
