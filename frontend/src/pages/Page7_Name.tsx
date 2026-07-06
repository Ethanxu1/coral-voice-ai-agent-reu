import { useState, useEffect } from 'react'
import { DummyFrame } from './DummyStream'
import { TextEntry } from './TextEntry'
import type { PageProps } from './TestUIRouter'

export default function Page7_Name({ state, submitText }: PageProps) {
  // The name the child just spoke (set once the transcript arrives), else show
  // a listening placeholder.
  const name = state.poseName?.trim()
  const target = name ? `"${name}"` : ''
  const [displayed, setDisplayed] = useState('')
  const listening = state.recording || state.recordStatus === 'recording'

  /* Typewriter the real transcribed name once it's available. */
  useEffect(() => {
    if (!target) {
      setDisplayed('')
      return
    }
    let i = 0
    setDisplayed('')
    const id = setInterval(() => {
      i++
      setDisplayed(target.slice(0, i))
      if (i >= target.length) clearInterval(id)
    }, 90)
    return () => clearInterval(id)
  }, [target])

  // The frame captured for this pose (real photo when available).
  const frame = state.classifyResult?.imageB64

  // Text mode, still waiting for the typed name → show a text box instead of the
  // "listening" microphone indicator.
  const textEntry = state.inputMode === 'text' && state.awaitingText

  return (
    <div className="tui-page p7-layout">
      {/* Quote display — the spoken name */}
      <div className="p7-quote-wrap tui-pop">
        <span className="p7-quote-mark">"</span>
        <span className="p7-quote-text" style={{ minHeight: '1.2em' }}>
          {displayed || <span style={{ opacity: 0.35 }}>{listening ? 'listening…' : '…'}</span>}
          <span
            style={{
              display: 'inline-block',
              width: 3,
              height: '1em',
              background: '#6a5acd',
              marginLeft: 2,
              verticalAlign: 'text-bottom',
              animation: 'tui-blink 0.8s step-end infinite',
            }}
          />
        </span>
        <span className="p7-quote-mark">"</span>
      </div>

      {/* Captured frame for this pose */}
      {frame ? (
        <img
          className="p7-frame-wrap"
          src={`data:image/jpeg;base64,${frame}`}
          alt="Captured pose"
          style={{ flex: 1, maxWidth: 700, objectFit: 'contain' }}
        />
      ) : (
        <DummyFrame className="p7-frame-wrap" style={{ flex: 1, maxWidth: 700 }} />
      )}

      {/* Input affordance: text box (text mode) or listening indicator (voice) */}
      {textEntry ? (
        <TextEntry
          prompt={state.caption || 'Type a name for this pose'}
          placeholder="e.g. Super Star"
          onSubmit={submitText}
        />
      ) : (
        <div className="p7-recording tui-pop" style={{ animationDelay: '0.2s' }}>
          <div className="p7-rec-dot" />
          <span>{listening ? '🎤 Listening for the name…' : '✅ Got it!'}</span>
        </div>
      )}
    </div>
  )
}
