export interface Landmark {
  x: number
  y: number
  z: number
  visibility: number
  xw?: number
  yw?: number
  zw?: number
}

export interface Project {
  id: string
  name: string
  schema_version: number
  settings: { output_mode: 'simulator' | 'live_robot' }
  created_at: string
  updated_at: string
}

export interface HumanPose {
  id: string
  project_id: string
  name: string
  thumbnail_svg: string
  min_confidence: number
  hold_seconds: number
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface RobotPose {
  id: string
  project_id: string
  name: string
  joints: Record<string, number>
  thumbnail_svg: string
  source: 'human' | 'simulator'
  safety: Record<string, unknown>
}

export interface SequenceStep {
  id?: string
  robot_pose_id: string
  position?: number
  hold_ms: number
  transition_ms: number
}

export interface MotionSequence {
  id: string
  project_id: string
  name: string
  steps: SequenceStep[]
  created_at: string
  updated_at: string
}

export interface BehaviorRule {
  id: string
  project_id: string
  human_pose_id: string
  sequence_id: string
  cooldown_seconds: number
  priority: number
  enabled: boolean
}

export interface ProjectPackage {
  schema_version: 1
  project: Record<string, unknown>
  human_poses: HumanPose[]
  training_samples: Record<string, unknown>[]
  robot_poses: RobotPose[]
  sequences: MotionSequence[]
  rules: BehaviorRule[]
  settings: { output_mode: 'simulator' | 'live_robot' }
}

export type OutputMode = 'simulator' | 'live_robot'

export interface MirrorSafety {
  fall_blocked: boolean
  collision_clamped: boolean
  rate_limited?: boolean
  safe_fraction: number
  bad_pairs: string[]
}

export interface MirrorPoseResult {
  status: 'done' | 'blocked'
  targets: Record<string, number>
  safety: MirrorSafety
}

export type StudioEvent =
  | { type: 'recognition'; subjectId: string; label: string | null; confidence: number; reason?: string }
  | { type: 'hold_progress'; subjectId: string; label?: string; progress: number }
  | { type: 'execution_started'; sequenceId: string }
  | { type: 'execution_completed'; sequenceId: string; message?: string }
  | { type: 'execution_blocked'; sequenceId: string; failedStep?: number; message: string }
  | { type: 'hardware_unavailable'; sequenceId: string; message: string }

export interface StudioSocketState {
  connected: boolean
  latestEvent: StudioEvent | null
  recognition: Record<string, { label: string | null; confidence: number; reason?: string }>
  holds: Record<string, number>
  executingSequenceId: string | null
  statusMessage: string | null
}
