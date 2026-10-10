import type {
  BehaviorRule,
  HumanPose,
  MotionSequence,
  OutputMode,
  Project,
  ProjectPackage,
  RobotPose,
  SequenceStep,
} from './types'

const STUDIO_BASE = import.meta.env.VITE_STUDIO_BASE ?? 'http://localhost:8000/studio'
const VISION_BASE = import.meta.env.VITE_VISION_BASE ?? 'http://localhost:8001'

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
    const detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    throw new Error(detail || `Studio request failed (${response.status})`)
  }
  return response.json() as Promise<T>
}

export const studioApi = {
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
  captureRetargetedPose: async () => {
    const response = await fetch(`${VISION_BASE}/map-features?leg_mode=retarget`, { method: 'POST' })
    const body = await response.json()
    if (!response.ok || !body.pose_detected) {
      throw new Error(body.detail ?? 'Full body not visible')
    }
    return body as { targets: Record<string, number>; body_landmarks: unknown[] }
  },
  listRobotPoses: (projectId: string) =>
    request<RobotPose[]>(`/robot-poses?project_id=${encodeURIComponent(projectId)}`),
  createRobotPose: (payload: Omit<RobotPose, 'id' | 'safety'> & { safety?: Record<string, unknown> }) =>
    request<RobotPose>('/robot-poses', { method: 'POST', body: JSON.stringify(payload) }),
  deleteRobotPose: (poseId: string) =>
    request<{ deleted: boolean }>(`/robot-poses/${poseId}`, { method: 'DELETE' }),
  listSequences: (projectId: string) =>
    request<MotionSequence[]>(`/sequences?project_id=${encodeURIComponent(projectId)}`),
  createSequence: (payload: { project_id: string; name: string; steps: SequenceStep[] }) =>
    request<MotionSequence>('/sequences', { method: 'POST', body: JSON.stringify(payload) }),
  previewSequence: (sequenceId: string) =>
    request<{ status: string; failed_step?: number }>(`/sequences/${sequenceId}/preview`, {
      method: 'POST',
    }),
  listRules: (projectId: string) =>
    request<BehaviorRule[]>(`/rules?project_id=${encodeURIComponent(projectId)}`),
  createRule: (payload: Omit<BehaviorRule, 'id'>) =>
    request<BehaviorRule>('/rules', { method: 'POST', body: JSON.stringify(payload) }),
  getOutputMode: () => request<{ mode: OutputMode }>('/output-mode'),
  setOutputMode: (mode: OutputMode) =>
    request<{ mode: OutputMode }>('/output-mode', {
      method: 'PUT',
      body: JSON.stringify({ mode }),
    }),
}
