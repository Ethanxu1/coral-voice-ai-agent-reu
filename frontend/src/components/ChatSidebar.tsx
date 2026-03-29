import { useState, useRef, useEffect } from 'react'

interface Message {
  role: 'user' | 'assistant'
  content: string
  commands?: string[]
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

  const highlightCommands = (content: string) => {
    // Highlight [COMMAND:xxx] patterns
    const pattern = /\[COMMAND:(\w+)\]/g
    const parts = content.split(pattern)

    return parts.map((part, index) => {
      // Every odd index is a captured command
      if (index % 2 === 1) {
        return (
          <span key={index} className="command-tag">
            {part}
          </span>
        )
      }
      return part
    })
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
            <div className="message-content">{highlightCommands(msg.content)}</div>
            {msg.commands && msg.commands.length > 0 && (
              <div className="message-commands">
                {msg.commands.map((cmd, cmdIndex) => (
                  <span key={cmdIndex} className="command-tag">
                    {cmd}
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
