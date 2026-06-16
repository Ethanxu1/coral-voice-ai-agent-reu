import { useState, useRef, useEffect, useCallback } from 'react'
import { useAudioVAD } from '../utils/useAudioVAD'

interface WaypointInfo {
  waypoint_index: number
  primitive_name: string | null
  angle: number | null
  joints: { [key: string]: number }
  speed: number
}

interface Message {
  role: 'user' | 'assistant'
  content: string
  waypoints?: WaypointInfo[]
  audioUrl?: string
}

interface ChatSidebarProps {
  messages: Message[]
  onSendMessage: (message: string) => void
  onSendAudio?: (blob: Blob) => void
  isConnected: boolean
  isLoading: boolean
}

function ChatSidebar({
  messages,
  onSendMessage,
  onSendAudio,
  isConnected,
  isLoading,
}: ChatSidebarProps) {
  const [input, setInput] = useState('')
  const [isRecording, setIsRecording] = useState(false)
  const [isInitializing, setIsInitializing] = useState(false)
  const [isAutoListening, setIsAutoListening] = useState(false)
  const [vadSpeechActive, setVadSpeechActive] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const audioChunksRef = useRef<Blob[]>([])

  const vad = useAudioVAD({
    onSpeechStart: () => setVadSpeechActive(true),
    onSpeechEnd: (blob: Blob) => {
      setVadSpeechActive(false)
      if (!isConnected || isLoading) return
      onSendAudio?.(blob)
    },
  })

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (input.trim() && isConnected && !isLoading) {
      onSendMessage(input.trim())
      setInput('')
    }
  }

  const startRecording = useCallback(async () => {
    setIsInitializing(true)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      audioChunksRef.current = []
      const recorder = new MediaRecorder(stream)
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data)
      }
      recorder.onstop = () => {
        const blob = new Blob(audioChunksRef.current, { type: 'audio/webm' })
        onSendAudio?.(blob)
        stream.getTracks().forEach((t) => t.stop())
        setIsRecording(false)
      }
      recorder.start()
      mediaRecorderRef.current = recorder
      // Brief warmup delay so the mic hardware is actually capturing before we signal "ready"
      await new Promise((resolve) => setTimeout(resolve, 400))
      setIsInitializing(false)
      setIsRecording(true)
    } catch {
      console.error('Microphone access denied')
      setIsInitializing(false)
    }
  }, [onSendAudio])

  const stopRecording = useCallback(() => {
    mediaRecorderRef.current?.stop()
  }, [])

  const toggleAutoListen = useCallback(() => {
    if (isAutoListening) {
      vad.pause()
      setIsAutoListening(false)
      setVadSpeechActive(false)
    } else {
      if (isRecording || isInitializing) return
      vad.start()
      setIsAutoListening(true)
    }
  }, [isAutoListening, isRecording, isInitializing, vad])

  const highlightWaypoints = (content: string) => {
    // Highlight [WAYPOINT: {...}, speed] patterns
    const pattern = /(\[WAYPOINT:\s*\{[^}]+\}(?:\s*,\s*\d+(?:\.\d+)?)?\s*\])/gi
    const parts = content.split(pattern)

    return parts.map((part, index) => {
      if (pattern.test(part)) {
        // Reset lastIndex since we're reusing the regex
        pattern.lastIndex = 0
        return (
          <span key={index} className="waypoint-tag">
            {part}
          </span>
        )
      }
      // Reset lastIndex for next iteration
      pattern.lastIndex = 0
      return part
    })
  }

  const formatWaypointSummary = (waypoint: WaypointInfo) => {
    const name = waypoint.primitive_name ?? 'direct'
    const angle = waypoint.angle != null ? ` ${waypoint.angle}°` : ''
    return `${name}${angle} speed=${waypoint.speed}`
  }

  return (
    <div className="panel" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <h2>Chat with G1 Robot</h2>

      <div className="messages">
        {messages.length === 0 && (
          <div style={{ color: '#666', textAlign: 'center', marginTop: '2rem' }}>
            <p>Start a conversation with the robot!</p>
            <p style={{ fontSize: '0.85rem', marginTop: '0.5rem' }}>
              Try: "Wave at me" or "Raise your right arm"
            </p>
          </div>
        )}

        {messages.map((msg, index) => (
          <div key={index} className={`message ${msg.role}`}>
            <div className="message-content">{highlightWaypoints(msg.content)}</div>
            {msg.audioUrl && (
              <button
                className="audio-playback-btn"
                onClick={() => new Audio(msg.audioUrl).play()}
                title="Play recorded audio"
              >
                <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor">
                  <polygon points="2,1 11,6 2,11" />
                </svg>
                Play recording
              </button>
            )}
            {msg.waypoints && msg.waypoints.length > 0 && (
              <div className="message-waypoints">
                <span className="waypoints-label">Executed:</span>
                {msg.waypoints.map((wp, wpIndex) => (
                  <span key={wpIndex} className="waypoint-tag executed">
                    WP{wp.waypoint_index + 1}: {formatWaypointSummary(wp)}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}

        {isLoading && (
          <div className="message assistant">
            <div className="message-content" style={{ fontStyle: 'italic', color: '#888' }}>
              Thinking...
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <form onSubmit={handleSubmit} className="chat-input-container">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={
            isInitializing ? 'Starting microphone...' :
            isRecording ? 'Listening (push-to-talk)...' :
            isAutoListening ? (vadSpeechActive ? 'Speaking detected...' : 'Listening for speech...') :
            isConnected ? 'Type a message...' : 'Connecting...'
          }
          className="chat-input"
          disabled={!isConnected || isLoading || isRecording || isInitializing || isAutoListening}
        />
        {onSendAudio && (
          <>
          <button
            type="button"
            className={`mic-btn${isInitializing ? ' initializing' : isRecording ? ' recording' : ''}`}
            disabled={!isConnected || isLoading || isInitializing || isAutoListening}
            onClick={isRecording ? stopRecording : startRecording}
            title={isInitializing ? 'Starting microphone...' : isRecording ? 'Stop recording' : 'Start recording'}
          >
            {isInitializing ? (
              <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeWidth="2" strokeDasharray="20 10">
                  <animateTransform attributeName="transform" type="rotate" from="0 8 8" to="360 8 8" dur="0.8s" repeatCount="indefinite" />
                </circle>
              </svg>
            ) : isRecording ? (
              <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                <rect x="3" y="3" width="10" height="10" rx="2" />
              </svg>
            ) : (
              <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                <rect x="5" y="1" width="6" height="9" rx="3" />
                <path d="M2.5 8a5.5 5.5 0 0 0 11 0h-1.5a4 4 0 0 1-8 0H2.5z" />
                <rect x="7.25" y="13" width="1.5" height="2" />
              </svg>
            )}
          </button>
          <button
            type="button"
            className={`mic-btn${isAutoListening ? (vadSpeechActive ? ' recording' : ' auto-listening') : ''}`}
            disabled={!isConnected || isLoading || isRecording || isInitializing}
            onClick={toggleAutoListen}
            title={isAutoListening ? 'Stop auto-listen' : 'Auto-listen (VAD)'}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
              <rect x="1" y="5" width="2" height="6" rx="1"/>
              <rect x="4" y="3" width="2" height="10" rx="1"/>
              <rect x="7" y="1" width="2" height="14" rx="1"/>
              <rect x="10" y="3" width="2" height="10" rx="1"/>
              <rect x="13" y="5" width="2" height="6" rx="1"/>
            </svg>
          </button>
          </>
        )}
        <button
          type="submit"
          className="send-btn"
          disabled={!isConnected || isLoading || !input.trim() || isRecording}
        >
          Send
        </button>
      </form>
    </div>
  )
}

export default ChatSidebar
