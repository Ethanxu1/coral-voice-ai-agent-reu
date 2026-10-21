import { useEffect, useRef } from 'react'
import type { RefinedChatMsg } from '../demo/useRefinedDemoMachine'

export default function ChatArea({
  messages,
  onChip,
  agentTyping,
}: {
  messages: RefinedChatMsg[]
  onChip: (text: string) => void
  agentTyping: boolean
}) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, agentTyping])

  return (
    <div className="rd-chat-area">
      {messages.map((msg, i) => (
        <ChatMsg key={i} msg={msg} onChip={onChip} />
      ))}
      {agentTyping && <TypingIndicator />}
      <div ref={bottomRef} />
    </div>
  )
}

function TypingIndicator() {
  return (
    <div className="rd-msg agent">
      <div className="rd-bubble rd-typing" aria-label="Agent is typing">
        <span className="rd-typing-dot" />
        <span className="rd-typing-dot" />
        <span className="rd-typing-dot" />
      </div>
    </div>
  )
}

function intentLabel(type: string | undefined): string {
  switch (type) {
    case 'motion': return 'motion'
    case 'conversation': return 'conversation'
    case 'clarification': return 'clarification'
    case 'immediate': return 'system command'
    default: return type ?? 'unknown'
  }
}

function classifierLabel(c: 'regex' | 'llm' | undefined): string {
  return c === 'regex' ? 'regex' : c === 'llm' ? 'LLM' : ''
}

function ChatMsg({
  msg,
  onChip,
}: {
  msg: RefinedChatMsg
  onChip: (text: string) => void
}) {
  return (
    <div className={`rd-msg ${msg.role}`}>
      <div className="rd-bubble">
        {msg.text}
        {msg.audioUrl && (
          <button
            className="rd-audio-play-btn"
            onClick={() => new Audio(msg.audioUrl).play()}
            title={msg.role === 'child' ? 'Play recording' : 'Play robot voice'}
            aria-label={msg.role === 'child' ? 'Play recording' : 'Play robot voice'}
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
              <polygon points="2,1 12,7 2,13" />
            </svg>
          </button>
        )}
      </div>
      {msg.role === 'child' && msg.intentType && (
        <div
          className="rd-intent-meta"
          title={msg.intentReason || 'Intent classification metadata'}
        >
          <span className={`rd-intent-badge rd-intent-type-${msg.intentType}`}>
            {intentLabel(msg.intentType)}
          </span>
          <span className={`rd-intent-badge rd-intent-classifier-${msg.intentClassifier}`}>
            {classifierLabel(msg.intentClassifier)}
          </span>
        </div>
      )}
      {msg.chips && msg.chips.length > 0 && (
        <div className="rd-chips">
          {msg.chips.map((chip) => (
            <button key={chip} className="rd-chip" onClick={() => onChip(chip)}>
              {chip}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
