import type {
  BehaviorRule,
  HumanPose,
  MotionSequence,
  MirrorPoseResult,
  OutputMode,
  Project,
  ProjectPackage,
  RobotPose,
  SequenceStep,
} from './types'

const STUDIO_BASE = import.meta.env.VITE_STUDIO_BASE ?? 'http://localhost:8000/studio'
const BACKEND_BASE = import.meta.env.VITE_BACKEND_BASE ?? 'http://localhost:8000'
const VISION_BASE = import.meta.env.VITE_VISION_BASE ?? 'http://localhost:8001'
const UPPER_BODY_ARM_SERVO_IDS = new Set([13, 14, 15, 16, 17, 18, 19, 20])
const MIRROR_TRANSITION_MS = 400

export const visionVideoFeedUrl = `${VISION_BASE}/video_feed`
export const visionUpperBodyFeedUrl = `${VISION_BASE}/video_feed?overlay=upper_body`

function describeErrorDetail(detail: unknown, fallback: string): string {
  if (typeof detail === 'string' && detail.trim()) return detail
  if (detail && typeof detail === 'object') {
    const record = detail as Record<string, unknown>
    const dependents = Array.isArray(record.dependents) ? record.dependents : []
    if (dependents.length > 0) {
      return `This pose is used by ${dependents.length} saved sequence or rule. Remove that reference first.`
    }
    const reason = String(record.reason ?? '')
    if (reason === 'collision_risk') return 'This pose would collide with the robot body. Try a wider pose.'
    if (reason === 'fall_risk') return 'This pose could make the robot fall. Try a more balanced pose.'
  }
  return fallback
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${STUDIO_BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.body ? { 'content-type': 'application/json' } : {}),
      ...init?.headers,
    },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(describeErrorDetail(body.detail, `Studio request failed (${response.status})`))
  }
  return response.json() as Promise<T>
}

async function visionRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${VISION_BASE}${path}`, init)
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(describeErrorDetail(body.detail, `Vision request failed (${response.status})`))
  }
  return response.json() as Promise<T>
}

export const studioApi = {
  resetSimulator: async () => {
    const response = await fetch(`${BACKEND_BASE}/reset?sim_only=true`, { method: 'POST' })
    const body = await response.json().catch(() => ({})) as Record<string, unknown>
    if (!response.ok || body.status !== 'done') {
      throw new Error(describeErrorDetail(
        body.detail,
        `Simulator reset failed (${response.status})`,
      ))
    }
  },
  getCameraState: () => visionRequest<{ enabled: boolean }>('/camera'),
  setCameraEnabled: (enabled: boolean) =>
    visionRequest<{ enabled: boolean }>(enabled ? '/camera/on' : '/camera/off', { method: 'POST' }),
  enterRobotPoseCapture: (sessionId: string) =>
    visionRequest<{ mode: string; session_id: string }>(
      `/studio/tracking/start?session_id=${encodeURIComponent(sessionId)}`,
      { method: 'POST' },
    ),
  exitRobotPoseCapture: (sessionId: string) =>
    visionRequest<{ mode: string; state: string; stale: boolean }>(
      `/studio/tracking/stop?session_id=${encodeURIComponent(sessionId)}`,
      { method: 'POST' },
    ),
  listProjects: () => request<Project[]>('/projects'),
  createProject: (name: string) =>
    request<Project>('/projects', { method: 'POST', body: JSON.stringify({ name }) }),
  exportProject: (projectId: string) =>
    request<ProjectPackage>(`/projects/${projectId}/export`),
  importProject: (payload: ProjectPackage) =>
    request<{ project_id: string }>('/projects/import', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  listHumanPoses: (projectId: string) =>
    request<HumanPose[]>(`/human-poses?project_id=${encodeURIComponent(projectId)}`),
  createHumanPose: (payload: {
    project_id: string
    name: string
    min_confidence?: number
    hold_seconds?: number
    thumbnail_svg?: string
  }) => request<HumanPose>('/human-poses', { method: 'POST', body: JSON.stringify(payload) }),
  addHumanPoseSample: (poseId: string, landmarks: unknown[]) =>
    request(`/human-poses/${poseId}/samples`, {
      method: 'POST',
      body: JSON.stringify({ landmarks }),
    }),
  deleteHumanPose: (poseId: string) =>
    request<{ deleted: boolean }>(`/human-poses/${poseId}`, { method: 'DELETE' }),
  captureRetargetedPose: async (signal?: AbortSignal) => {
    const response = await fetch(`${VISION_BASE}/map-features?upper_body_only=true`, {
      method: 'POST',
      signal,
    })
    const body = await response.json()
    if (!response.ok || !body.pose_detected) {
      throw new Error(describeErrorDetail(body.detail, 'Upper body not visible'))
    }
    return body as {
      targets: Record<string, number>
      commands: { servo_id: number; position: number; duration_ms: number }[]
      body_landmarks: unknown[]
    }
  },
  mirrorRetargetedPose: async (signal?: AbortSignal): Promise<MirrorPoseResult> => {
    const captured = await studioApi.captureRetargetedPose(signal)
    const armCommands = captured.commands.filter((command) => (
      UPPER_BODY_ARM_SERVO_IDS.has(command.servo_id)
    ))
    if (armCommands.length === 0) throw new Error('No robot arm joints could be mapped')
    const response = await fetch(`${BACKEND_BASE}/move`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      signal,
      body: JSON.stringify({
        moves: armCommands.map((command) => ({
          ...command,
          duration_ms: MIRROR_TRANSITION_MS,
        })),
        sim_only: true,
        stabilized_preview: true,
      }),
    })
    const body = await response.json().catch(() => ({}))
    if (!response.ok) {
      throw new Error(describeErrorDetail(body.detail, `Live mirror failed (${response.status})`))
    }
    if (
      !body
      || (body.status !== 'done' && body.status !== 'blocked')
      || !body.targets
      || !body.safety
    ) {
      throw new Error(describeErrorDetail(body?.detail, 'Live mirror returned an invalid response'))
    }
    return body as MirrorPoseResult
  },
  listRobotPoses: (projectId: string) =>
    request<RobotPose[]>(`/robot-poses?project_id=${encodeURIComponent(projectId)}`),
  createRobotPose: (payload: Omit<RobotPose, 'id' | 'safety'> & { safety?: Record<string, unknown> }) =>
    request<RobotPose>('/robot-poses', { method: 'POST', body: JSON.stringify(payload) }),
  previewRobotPose: (poseId: string) =>
    request<{ status: string; reason?: string | null }>(`/robot-poses/${poseId}/preview`, {
      method: 'POST',
    }),
  deleteRobotPose: (poseId: string) =>
    request<{ deleted: boolean }>(`/robot-poses/${poseId}`, { method: 'DELETE' }),
  listSequences: (projectId: string) =>
    request<MotionSequence[]>(`/sequences?project_id=${encodeURIComponent(projectId)}`),
  createSequence: (payload: { project_id: string; name: string; steps: SequenceStep[] }) =>
    request<MotionSequence>('/sequences', { method: 'POST', body: JSON.stringify(payload) }),
  updateSequence: (sequenceId: string, payload: { name: string; steps: SequenceStep[] }) =>
    request<MotionSequence>(`/sequences/${sequenceId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  deleteSequence: (sequenceId: string) =>
    request<{ deleted: boolean }>(`/sequences/${sequenceId}`, { method: 'DELETE' }),
  previewSequence: (sequenceId: string) =>
    request<{ status: string; completed_steps: number; failed_step?: number; reason?: string | null }>(`/sequences/${sequenceId}/preview`, {
      method: 'POST',
    }),
  listRules: (projectId: string) =>
    request<BehaviorRule[]>(`/rules?project_id=${encodeURIComponent(projectId)}`),
  createRule: (payload: Omit<BehaviorRule, 'id'>) =>
    request<BehaviorRule>('/rules', { method: 'POST', body: JSON.stringify(payload) }),
  deleteInteraction: (ruleId: string) =>
    request<{ deleted: boolean }>(`/interactions/${ruleId}`, { method: 'DELETE' }),
  reorderInteractions: (payload: { project_id: string; rule_ids: string[] }) =>
    request<{ reordered: boolean }>('/interactions/order', {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  getOutputMode: () => request<{ mode: OutputMode }>('/output-mode'),
  setOutputMode: (mode: OutputMode) =>
    request<{ mode: OutputMode }>('/output-mode', {
      method: 'PUT',
      body: JSON.stringify({ mode }),
    }),
  getTriggerMode: () => request<{ enabled: boolean }>('/trigger-mode'),
  setTriggerMode: (enabled: boolean) =>
    request<{ enabled: boolean }>('/trigger-mode', {
      method: 'PUT',
      body: JSON.stringify({ enabled }),
    }),
}
