import { useState, useEffect } from 'react'

const FEED_URL = 'http://localhost:8001/video_feed'

export default function CameraFeed() {
  const [key, setKey] = useState(0)

  useEffect(() => {
    const interval = setInterval(() => {
      // Reload image if it stops streaming
    }, 30000)
    return () => clearInterval(interval)
  }, [])

  return (
    <div style={{ position: 'relative', background: '#111', borderRadius: 8, overflow: 'hidden' }}>
      <img
        key={key}
        src={FEED_URL}
        alt="Camera feed with pose overlay"
        style={{ width: '100%', display: 'block' }}
        onError={() => setTimeout(() => setKey(k => k + 1), 2000)}
      />
      <div style={{
        position: 'absolute', top: 8, left: 8,
        background: 'rgba(0,0,0,0.6)', color: '#0f0', fontSize: 11,
        padding: '2px 6px', borderRadius: 4, fontFamily: 'monospace'
      }}>
        LIVE
      </div>
    </div>
  )
}
