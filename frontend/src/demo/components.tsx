// Presentational pieces for the Demo page. Kept dumb — they render from props
// only; all orchestration lives in useDemoMachine.

import { useState } from 'react'
import type { ClassifyResult } from './api'
import { ROBOT_STREAM } from './config'
import type { RecordStatus } from './useDemoMachine'

// Live annotated camera stream from the Pi vision node (MJPEG on :9001).
export function DemoCameraFeed() {
  const [key, setKey] = useState(0)
  return (
    <div className="demo-camera">
      <img
        key={key}
        src={`${ROBOT_STREAM}/video_feed`}
        alt="Live camera"
        onError={() => setTimeout(() => setKey((k) => k + 1), 2000)}
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

export function ClassifyCard({ result }: { result: ClassifyResult }) {
  const entries = Object.entries(result.probabilities).sort((a, b) => b[1] - a[1])
  return (
    <div className="demo-classify-card demo-pop">
      {result.imageB64 && (
        <img
          className="demo-classify-img"
          src={`data:image/jpeg;base64,${result.imageB64}`}
          alt="Classified pose"
        />
      )}
      <div className="demo-classify-info">
        <div className="demo-classify-title">{prettyClass(result.className)}</div>
        <div className="demo-bars">
          {entries.map(([cls, pct]) => (
            <div className="demo-bar-row" key={cls}>
              <span className="demo-bar-label">{prettyClass(cls)}</span>
              <div className="demo-bar-track">
                <div
                  className={`demo-bar-fill ${cls === result.className ? 'top' : ''}`}
                  style={{ width: `${Math.max(2, pct)}%` }}
                />
              </div>
              <span className="demo-bar-pct">{pct.toFixed(0)}%</span>
            </div>
          ))}
        </div>
      </div>
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
