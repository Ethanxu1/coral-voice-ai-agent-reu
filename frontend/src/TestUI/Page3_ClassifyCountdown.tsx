import { useEffect, useState } from 'react'
import { DummyStream } from './DummyStream'

export default function Page3_ClassifyCountdown() {
  const [count, setCount] = useState(3)

  useEffect(() => {
    const id = setInterval(() => {
      setCount((c) => (c <= 1 ? 3 : c - 1))
    }, 1400)
    return () => clearInterval(id)
  }, [])

  return (
    <div className="tui-page p3-layout">
      <DummyStream className="p3-stream-full" showPerson personWidth={260} />

      <div className="p3-countdown-overlay">
        <div key={count} className="p3-number">{count}</div>
      </div>

      {/* subtle top hint */}
      <div
        style={{
          position: 'absolute',
          top: 14,
          left: '50%',
          transform: 'translateX(-50%)',
          background: 'rgba(255,255,255,0.7)',
          backdropFilter: 'blur(6px)',
          borderRadius: 999,
          padding: '5px 18px',
          fontWeight: 800,
          fontSize: 14,
          color: '#6a5acd',
          whiteSpace: 'nowrap',
          zIndex: 6,
        }}
      >
        Hold your pose! 📸
      </div>
    </div>
  )
}
