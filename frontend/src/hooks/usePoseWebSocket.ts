import { useState, useEffect, useRef, useCallback } from 'react'
import type { Landmark, FaceLandmark, HeadPose, CalibrationStatus } from '../types/pose'

const VISION_BASE = 'http://localhost:8001'
const VISION_WS = 'ws://localhost:8001/ws/pose'

export function usePoseWebSocket() {
  const [bodyLandmarks, setBodyLandmarks] = useState<Landmark[]>([])
  const [faceLandmarks, setFaceLandmarks] = useState<FaceLandmark[]>([])
  const [headPose, setHeadPose] = useState<HeadPose | null>(null)
  const [calibrationStatus, setCalibrationStatus] = useState<CalibrationStatus>({
    state: 'idle',
    progress: 0,
    frame_count: 0,
  })
  const [isConnected, setIsConnected] = useState(false)
  const [trackingLost, setTrackingLost] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectRef = useRef<number | null>(null)

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return
    const ws = new WebSocket(VISION_WS)
    wsRef.current = ws

    ws.onopen = () => setIsConnected(true)
    ws.onclose = () => {
      setIsConnected(false)
      reconnectRef.current = window.setTimeout(connect, 2000)
    }
    ws.onerror = () => ws.close()
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      if (data.type === 'pose_update') {
        setTrackingLost(false)
        if (data.body_landmarks?.length) setBodyLandmarks(data.body_landmarks)
        if (data.face_landmarks?.length) setFaceLandmarks(data.face_landmarks)
        setHeadPose(data.head_pose)
        if (data.calibration) setCalibrationStatus(data.calibration)
      } else if (data.type === 'tracking_lost') {
        setTrackingLost(true)
      } else if (data.type === 'calibration_status') {
        setCalibrationStatus({ state: data.state, progress: data.progress, frame_count: data.frame_count ?? 0 })
      }
    }
  }, [])

  useEffect(() => {
    connect()
    return () => {
      if (reconnectRef.current) clearTimeout(reconnectRef.current)
      wsRef.current?.close()
    }
  }, [connect])

  const startCalibration = useCallback(async () => {
    await fetch(`${VISION_BASE}/calibrate/start`, { method: 'POST' })
  }, [])

  const resetCalibration = useCallback(async () => {
    await fetch(`${VISION_BASE}/calibrate/reset`, { method: 'POST' })
  }, [])

  return {
    bodyLandmarks,
    faceLandmarks,
    headPose,
    calibrationStatus,
    isConnected,
    trackingLost,
    startCalibration,
    resetCalibration,
  }
}
