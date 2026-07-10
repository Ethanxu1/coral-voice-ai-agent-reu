import { useState, useEffect, useRef, useCallback } from 'react'
import { Routes, Route, Link, Navigate } from 'react-router-dom'
import SimulatorControls from './components/SimulatorControls'
import ChatSidebar from './components/ChatSidebar'
import HomeVisionPanel from './components/HomeVisionPanel'
import PoseVisualization from './pages/PoseVisualization'
import ProDemo from './pages/ProDemo'
import RefinedDemo from './pages/RefinedDemo'
import Tutorial from './pages/Tutorial'
import MoveMate from './pages/MoveMate'
import RobotModeToggle from './components/RobotModeToggle'

interface WaypointInfo {
  waypoint_index: number
  joints: { [key: string]: number }
  speed: number
}

interface Message {
  role: 'user' | 'assistant'
  content: string
  waypoints?: WaypointInfo[]
  audioUrl?: string
}

interface JointStates {
  [key: string]: number
}

function App() {
  const [messages, setMessages] = useState<Message[]>([])
  const [jointStates, setJointStates] = useState<JointStates>({})
  const [isConnected, setIsConnected] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [followActive, setFollowActive] = useState(false)
  const [captureStage, setCaptureStage] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<number | null>(null)
  const pendingAudioUrlRef = useRef<string | null>(null)

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    const ws = new WebSocket('ws://localhost:8000/ws')

    ws.onopen = () => {
      console.log('WebSocket connected')
      setIsConnected(true)
      // Request initial state
      ws.send(JSON.stringify({ type: 'get_state' }))
    }

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      console.log('Received:', data)

      if (data.type === 'transcription') {
        if (data.text?.trim()) {
          const audioUrl = pendingAudioUrlRef.current ?? undefined
          pendingAudioUrlRef.current = null
          setMessages((prev) => [...prev, { role: 'user', content: data.text, audioUrl }])
          setIsLoading(true)
        } else {
          pendingAudioUrlRef.current = null
        }
      } else if (data.type === 'chat_response') {
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: data.content,
            waypoints: data.waypoints,
          },
        ])
        if (data.joint_states) {
          setJointStates(data.joint_states)
        }
        setIsLoading(false)
      } else if (data.type === 'command_result') {
        if (data.joint_states) {
          setJointStates(data.joint_states)
        }
      } else if (data.type === 'state') {
        if (data.joint_states) {
          setJointStates(data.joint_states)
        }
      } else if (data.type === 'follow_status') {
        setFollowActive(!!data.active)
      } else if (data.type === 'capture_status') {
        setCaptureStage(data.stage ?? null)
        if (data.stage === 'done' || data.stage === 'error') {
          setTimeout(() => setCaptureStage(null), 2000)
        }
      }
    }

    ws.onclose = () => {
      console.log('WebSocket disconnected')
      setIsConnected(false)
      wsRef.current = null
      // Attempt to reconnect after 2 seconds
      reconnectTimeoutRef.current = window.setTimeout(() => {
        connect()
      }, 2000)
    }

    ws.onerror = (error) => {
      console.error('WebSocket error:', error)
    }

    wsRef.current = ws
  }, [])

  useEffect(() => {
    connect()

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
      }
      if (wsRef.current) {
        wsRef.current.close()
      }
    }
  }, [connect])

  const sendCommand = useCallback((command: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'command', command }))
    }
  }, [])

  const sendMessage = useCallback((content: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      setMessages((prev) => [...prev, { role: 'user', content }])
      setIsLoading(true)
      wsRef.current.send(JSON.stringify({ type: 'chat', content }))
    }
  }, [])

  const sendAudio = useCallback((blob: Blob) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      pendingAudioUrlRef.current = URL.createObjectURL(blob)
      const reader = new FileReader()
      reader.onloadend = () => {
        const base64 = (reader.result as string).split(',')[1]
        wsRef.current?.send(JSON.stringify({ type: 'audio', data: base64, format: 'webm' }))
      }
      reader.readAsDataURL(blob)
    }
  }, [])

  const handleToggleFollow = useCallback(() => {
    const phrase = followActive ? 'stop following' : 'follow my movement'
    sendMessage(phrase)
  }, [followActive, sendMessage])

  const handleCapturePose = useCallback(() => {
    sendMessage('capture pose')
  }, [sendMessage])

  const mainView = (
    <div className="app">
      <HomeVisionPanel
        followActive={followActive}
        captureStage={captureStage}
        onCapturePose={handleCapturePose}
        onToggleFollow={handleToggleFollow}
      />
      <div className="chat-panel">
        <ChatSidebar
          messages={messages}
          onSendMessage={sendMessage}
          onSendAudio={sendAudio}
          isConnected={isConnected}
          isLoading={isLoading}
        />
      </div>
      <div className="controls-panel">
        <SimulatorControls
          onCommand={sendCommand}
          isConnected={isConnected}
          jointStates={jointStates}
        />
        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          <Link to="/tutorial" style={{ textDecoration: 'none' }}>
            <button className="primitives-test-btn">📚 Tutorial</button>
          </Link>
          <Link to="/pose" style={{ textDecoration: 'none' }}>
            <button className="primitives-test-btn">Pose Tracking</button>
          </Link>
          <Link to="/prodemo" state={{ fromApp: true }} style={{ textDecoration: 'none' }}>
            <button className="primitives-test-btn">🧪 Pro Demo</button>
          </Link>
          <Link to="/refineddemo" state={{ fromApp: true }} style={{ textDecoration: 'none' }}>
            <button className="primitives-test-btn">✨ Refined Demo</button>
          </Link>
        </div>
        <RobotModeToggle />
      </div>
    </div>
  )

  return (
    <Routes>
      <Route path="/" element={mainView} />
      <Route path="/pose" element={<PoseVisualization />} />
      <Route path="/prodemo" element={<ProDemo />} />
      <Route path="/refineddemo" element={<RefinedDemo />} />
      <Route path="/tutorial" element={<Tutorial />} />
      <Route path="/movemate" element={<MoveMate />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default App
