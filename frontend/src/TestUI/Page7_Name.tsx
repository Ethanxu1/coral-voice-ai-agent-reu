import { useState, useEffect } from 'react'
import { DummyFrame } from './DummyStream'

const EXAMPLE_TEXT = '"T-Pose"'

export default function Page7_Name() {
  const [displayed, setDisplayed] = useState('')

  /* Typewriter effect for the pose name */
  useEffect(() => {
    let i = 0
    setDisplayed('')
    const id = setInterval(() => {
      i++
      setDisplayed(EXAMPLE_TEXT.slice(0, i))
      if (i >= EXAMPLE_TEXT.length) clearInterval(id)
    }, 90)
    return () => clearInterval(id)
  }, [])

  return (
    <div className="tui-page p7-layout">
      {/* Quote display */}
      <div className="p7-quote-wrap tui-pop">
        <span className="p7-quote-mark">"</span>
        <span className="p7-quote-text" style={{ minHeight: '1.2em' }}>
          {displayed || <span style={{ opacity: 0 }}>{EXAMPLE_TEXT}</span>}
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

      {/* Clean frame */}
      <DummyFrame
        className="p7-frame-wrap"
        style={{ flex: 1, maxWidth: 700 }}
      />

      {/* Recording indicator */}
      <div className="p7-recording tui-pop" style={{ animationDelay: '0.2s' }}>
        <div className="p7-rec-dot" />
        <span>🎤 Listening for the name…</span>
      </div>
    </div>
  )
}
