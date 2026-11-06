export interface Landmark {
  x: number
  y: number
  z: number
  visibility: number
}

export interface FaceLandmark {
  index: number
  name: string
  x: number
  y: number
}

export interface HeadPose {
  yaw: number
  pitch: number
  roll: number
}

export interface StabilityStatus {
  state: 'idle' | 'countdown' | 'collecting' | 'frozen'
  countdown_remaining: number
  collection_progress: number
}

export interface SubjectMetrics {
  face_sim: number | null
  app_sim: number | null
  face_det_score: number
  face_trusted: boolean
  path: 'fused' | 'face' | 'appearance' | 'legacy' | 'none'
  score: number | null
  passed: boolean
}

export interface DetectedSubject {
  id: string
  bbox: { x: number; y: number; width: number; height: number }
  is_candidate: boolean
  hold_progress: number
  depth?: number
  metrics?: SubjectMetrics | null
}

export interface TuningParamSpec {
  key: string
  label: string
  min: number
  max: number
  step: number
  hint: string
}

export type SelectionState = 'idle' | 'selecting' | 'selected' | 'searching'
