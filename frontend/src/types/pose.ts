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
  raw_yaw: number
  raw_pitch: number
  raw_roll: number
}

export interface CalibrationStatus {
  state: 'idle' | 'collecting' | 'calibrated'
  progress: number
  frame_count: number
}

export interface PoseUpdate {
  type: 'pose_update' | 'tracking_lost' | 'calibration_status'
  timestamp: number
  body_landmarks: Landmark[]
  face_landmarks: FaceLandmark[]
  head_pose: HeadPose | null
  calibration: CalibrationStatus
  reason?: string
  message?: string
}
