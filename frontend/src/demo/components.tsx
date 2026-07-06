// Presentational pieces for the Demo page. Kept dumb — they render from props
// only; all orchestration lives in useDemoMachine.

import { useState } from 'react'
import { useRobotConfig, getRobotStream } from './robotConfig'
import type { RecordStatus } from './useDemoMachine'

// Live annotated camera stream from the Pi vision node (MJPEG on :9001).
export function DemoCameraFeed() {
  const [key, setKey] = useState(0)
  useRobotConfig() // re-render so `src` picks up a sim/hardware mode change
  return (
    <div className="demo-camera">
      <img
        key={key}
        src={`${getRobotStream()}/video_feed`}
        alt="Live camera"
        onError={() => setTimeout(() => setKey((k) => k + 1), 2000)}
        style={{ transform: 'scaleX(-1)' }}
      />
      <span className="demo-live">● LIVE</span>
    </div>
  )
}

export function Countdown({ value }: { value: number | null }) {
  if (value == null) return null
  return (
    <div className="demo-overlay">
      <div key={value} className="demo-countdown">{value}</div>
    </div>
  )
}

export function CameraFlash({ active }: { active: boolean }) {
  if (!active) return null
  return <div className="demo-flash" />
}

export function SpeakingBubble({ speaking, caption }: { speaking: boolean; caption: string }) {
  return (
    <div className={`demo-caption ${speaking ? 'speaking' : ''}`}>
      <span className="demo-mascot" aria-hidden>🤖</span>
      <span className="demo-caption-text">{caption}</span>
    </div>
  )
}

export function RecordIndicator({ status }: { status: RecordStatus }) {
  const icon = status === 'recording' ? '🎤'
    : status === 'thinking' ? '💭'
    : status === 'action' ? '✅'
    : status === 'clarify' ? '🔁'
    : '🎤'
  return (
    <div className={`demo-record demo-record-${status}`}>
      <div className="demo-record-ring"><span>{icon}</span></div>
    </div>
  )
}

export function prettyClass(name: string): string {
  return name.replace(/[-_]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}
