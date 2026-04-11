import { useState, useRef, useEffect } from 'react'

interface WaypointInfo {
  waypoint_index: number
  joints: { [key: string]: number }
  speed: number
}

interface Message {
  role: 'user' | 'assistant'
  content: string
  waypoints?: WaypointInfo[]
}

interface ChatSidebarProps {
  messages: Message[]
  onSendMessage: (message: string) => void
  isConnected: boolean
  isLoading: boolean
}

function ChatSidebar({
  messages,
  onSendMessage,
  isConnected,
  isLoading,
}: ChatSidebarProps) {
  const [input, setInput] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)

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
    const jointCount = Object.keys(waypoint.joints).length
    const speedLabel = waypoint.speed < 0.7 ? 'slow' : waypoint.speed > 1.5 ? 'fast' : 'normal'
    return `${jointCount} joint${jointCount > 1 ? 's' : ''} (${speedLabel})`
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
          placeholder={isConnected ? 'Type a message...' : 'Connecting...'}
          className="chat-input"
          disabled={!isConnected || isLoading}
        />
        <button
          type="submit"
          className="send-btn"
          disabled={!isConnected || isLoading || !input.trim()}
        >
          Send
        </button>
      </form>
    </div>
  )
}

export default ChatSidebar
