import { useState, useEffect, useRef, useCallback } from 'react'
import type { Landmark, FaceLandmark, HeadPose, CalibrationStatus, StabilityStatus } from '../types/pose'

const VISION_BASE = 'http://localhost:8001'
const VISION_WS = 'ws://localhost:8001/ws/pose'

const INITIAL_STABILITY: StabilityStatus = {
  state: 'idle',
  countdown_remaining: 0,
  collection_progress: 0,
}

export function usePoseWebSocket() {
  const [bodyLandmarks, setBodyLandmarks] = useState<Landmark[]>([])
  const [faceLandmarks, setFaceLandmarks] = useState<FaceLandmark[]>([])
  const [headPose, setHeadPose] = useState<HeadPose | null>(null)
  const [calibrationStatus, setCalibrationStatus] = useState<CalibrationStatus>({
    state: 'idle',
    progress: 0,
    frame_count: 0,
  })
  const [stabilityStatus, setStabilityStatus] = useState<StabilityStatus>(INITIAL_STABILITY)
  const [isConnected, setIsConnected] = useState(false)
  const [trackingLost, setTrackingLost] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectRef = useRef<number | null>(null)
  const genRef = useRef(0)

  const connect = useCallback(() => {
    // Close any existing connection that isn't already closed
    if (wsRef.current && wsRef.current.readyState !== WebSocket.CLOSED) {
      wsRef.current.onclose = null
      wsRef.current.close()
    }
    const gen = ++genRef.current
    const ws = new WebSocket(VISION_WS)
    wsRef.current = ws

    ws.onopen = () => {
      if (gen !== genRef.current) return
      console.log('[pose ws] connected')
      setIsConnected(true)
    }
    ws.onclose = () => {
      if (gen !== genRef.current) return
      console.log('[pose ws] disconnected — retrying in 2s')
      setIsConnected(false)
      reconnectRef.current = window.setTimeout(connect, 2000)
    }
    ws.onerror = () => ws.close()
    ws.onmessage = (event) => {
      if (gen !== genRef.current) return
      const data = JSON.parse(event.data)
      if (data.type === 'ping') return
      if (data.type === 'pose_update') {
        setTrackingLost(false)
        // While frozen, backend publishes the stable-frame landmarks repeatedly,
        // so always taking the latest values naturally locks the 3D skeleton.
        if (data.body_landmarks?.length) setBodyLandmarks(data.body_landmarks)
        if (data.face_landmarks?.length) setFaceLandmarks(data.face_landmarks)
        setHeadPose(data.head_pose)
        if (data.calibration) setCalibrationStatus(data.calibration)
        if (data.stability) setStabilityStatus(data.stability)
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
      // Invalidate the current generation so no stale callbacks fire
      genRef.current++
      if (reconnectRef.current) clearTimeout(reconnectRef.current)
      if (wsRef.current) {
        wsRef.current.onclose = null
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, [connect])

  const startCalibration = useCallback(async () => {
    await fetch(`${VISION_BASE}/calibrate/start`, { method: 'POST' })
  }, [])

  const resetCalibration = useCallback(async () => {
    await fetch(`${VISION_BASE}/calibrate/reset`, { method: 'POST' })
  }, [])

  const captureStablePosition = useCallback(async () => {
    await fetch(`${VISION_BASE}/capture/stable_position/start`, { method: 'POST' })
  }, [])

  const continueLive = useCallback(async () => {
    await fetch(`${VISION_BASE}/capture/stable_position/continue`, { method: 'POST' })
  }, [])

  return {
    bodyLandmarks,
    faceLandmarks,
    headPose,
    calibrationStatus,
    stabilityStatus,
    isConnected,
    trackingLost,
    startCalibration,
    resetCalibration,
    captureStablePosition,
    continueLive,
  }
}
