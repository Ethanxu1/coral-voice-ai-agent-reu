import { useEffect, useRef } from 'react'
import type { Landmark, FaceLandmark, HeadPose } from '../../types/pose'

// MediaPipe Pose connections (from index pairs)
const POSE_CONNECTIONS: [number, number][] = [
  [0,1],[1,2],[2,3],[3,7],[0,4],[4,5],[5,6],[6,8],
  [9,10],[11,12],[11,13],[13,15],[15,17],[15,19],[15,21],[17,19],
  [12,14],[14,16],[16,18],[16,20],[16,22],[18,20],
  [11,23],[12,24],[23,24],[23,25],[24,26],[25,27],[26,28],
  [27,29],[28,30],[29,31],[30,32],[27,31],[28,32],
]

// Indices that represent head region (nose, eyes, ears, mouth)
const HEAD_INDICES = new Set([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
// Special highlight indices: nose=0, left ear=7, right ear=8
const SPECIAL_INDICES = new Set([0, 7, 8])

function visibilityColor(v: number): string {
  if (v > 0.8) return '#00ff88'
  if (v > 0.4) return '#ffcc00'
  return '#ff4444'
}

interface Props {
  landmarks: Landmark[]
  faceLandmarks: FaceLandmark[]
  headPose: HeadPose | null
}

export default function SkeletonCanvas({ landmarks, faceLandmarks, headPose }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    const container = containerRef.current
    if (!canvas || !container) return

    const observer = new ResizeObserver(() => {
      canvas.width = container.clientWidth
      canvas.height = container.clientHeight
    })
    observer.observe(container)
    canvas.width = container.clientWidth
    canvas.height = container.clientHeight
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !landmarks.length) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const W = canvas.width
    const H = canvas.height
    ctx.clearRect(0, 0, W, H)

    // Background
    ctx.fillStyle = '#0d0d0d'
    ctx.fillRect(0, 0, W, H)

    // Helper: landmark index → canvas coords
    const toXY = (idx: number): [number, number] => [
      landmarks[idx].x * W,
      landmarks[idx].y * H,
    ]

    // Draw bones
    for (const [a, b] of POSE_CONNECTIONS) {
      if (!landmarks[a] || !landmarks[b]) continue
      if (landmarks[a].visibility < 0.2 || landmarks[b].visibility < 0.2) continue
      const [ax, ay] = toXY(a)
      const [bx, by] = toXY(b)
      ctx.beginPath()
      ctx.moveTo(ax, ay)
      ctx.lineTo(bx, by)
      const avgVis = (landmarks[a].visibility + landmarks[b].visibility) / 2
      ctx.strokeStyle = `rgba(120,180,255,${Math.max(0.2, avgVis * 0.7)})`
      ctx.lineWidth = HEAD_INDICES.has(a) && HEAD_INDICES.has(b) ? 1.5 : 2
      ctx.stroke()
    }

    // Draw joints
    for (let i = 0; i < landmarks.length; i++) {
      const lm = landmarks[i]
      if (lm.visibility < 0.2) continue
      const [x, y] = toXY(i)
      ctx.beginPath()
      if (SPECIAL_INDICES.has(i)) {
        // Nose, ears — larger magenta
        ctx.arc(x, y, 7, 0, Math.PI * 2)
        ctx.fillStyle = '#ff00ff'
        ctx.fill()
        ctx.strokeStyle = '#ffffff'
        ctx.lineWidth = 1.5
        ctx.stroke()
      } else {
        ctx.arc(x, y, HEAD_INDICES.has(i) ? 4 : 5, 0, Math.PI * 2)
        ctx.fillStyle = visibilityColor(lm.visibility)
        ctx.fill()
      }
    }

    // Draw face PnP landmarks (nose_tip as larger dot with label)
    for (const fl of faceLandmarks) {
      const fx = fl.x * W
      const fy = fl.y * H
      ctx.beginPath()
      ctx.arc(fx, fy, fl.name === 'nose_tip' ? 9 : 5, 0, Math.PI * 2)
      ctx.fillStyle = 'rgba(255,0,255,0.5)'
      ctx.fill()
      ctx.strokeStyle = '#ff88ff'
      ctx.lineWidth = 1
      ctx.stroke()
      if (fl.name === 'nose_tip') {
        ctx.font = '10px monospace'
        ctx.fillStyle = '#ff88ff'
        ctx.fillText('nose', fx + 10, fy - 4)
      }
    }

    // Draw head orientation arrows from nose if pose available
    if (headPose && landmarks[0]?.visibility > 0.3) {
      const [nx, ny] = toXY(0)
      const scale = Math.min(W, H) * 0.12

      const drawArrow = (angle: number, color: string, label: string) => {
        const ex = nx + Math.cos(angle) * scale
        const ey = ny + Math.sin(angle) * scale
        ctx.beginPath()
        ctx.moveTo(nx, ny)
        ctx.lineTo(ex, ey)
        ctx.strokeStyle = color
        ctx.lineWidth = 2.5
        ctx.stroke()
        // Arrowhead
        const headLen = 10
        const da = 0.4
        ctx.beginPath()
        ctx.moveTo(ex, ey)
        ctx.lineTo(
          ex - headLen * Math.cos(angle - da),
          ey - headLen * Math.sin(angle - da),
        )
        ctx.moveTo(ex, ey)
        ctx.lineTo(
          ex - headLen * Math.cos(angle + da),
          ey - headLen * Math.sin(angle + da),
        )
        ctx.strokeStyle = color
        ctx.lineWidth = 2
        ctx.stroke()
        ctx.font = '10px monospace'
        ctx.fillStyle = color
        ctx.fillText(label, ex + 4, ey)
      }

      const yawRad = (headPose.yaw * Math.PI) / 180
      const pitchRad = (headPose.pitch * Math.PI) / 180

      drawArrow(-Math.PI / 2 + pitchRad, '#44ff44', `P${headPose.pitch.toFixed(0)}°`)
      drawArrow(yawRad, '#ff4444', `Y${headPose.yaw.toFixed(0)}°`)
    }

    // Label special head points
    const labelMap: Record<number, string> = { 0: 'nose', 7: 'L.ear', 8: 'R.ear' }
    for (const [idx, label] of Object.entries(labelMap)) {
      const lm = landmarks[parseInt(idx)]
      if (!lm || lm.visibility < 0.3) continue
      const [x, y] = toXY(parseInt(idx))
      ctx.font = '10px monospace'
      ctx.fillStyle = '#ff88ff'
      ctx.fillText(label, x + 10, y - 4)
    }

    // Estimate top-of-head: slightly above nose
    if (landmarks[0]?.visibility > 0.3) {
      const [nx, ny] = toXY(0)
      const topY = ny - (landmarks[0].y * H * 0.12)
      ctx.beginPath()
      ctx.arc(nx, topY, 6, 0, Math.PI * 2)
      ctx.fillStyle = '#ff00ff'
      ctx.fill()
      ctx.font = '10px monospace'
      ctx.fillStyle = '#ff88ff'
      ctx.fillText('top', nx + 8, topY - 4)
    }

    // Estimate chin: below nose using mouth landmarks if available
    if (landmarks[9] && landmarks[10] && landmarks[9].visibility > 0.3) {
      const cx = ((landmarks[9].x + landmarks[10].x) / 2) * W
      const cy = ((landmarks[9].y + landmarks[10].y) / 2) * H + 14
      ctx.beginPath()
      ctx.arc(cx, cy, 6, 0, Math.PI * 2)
      ctx.fillStyle = '#ff00ff'
      ctx.fill()
      ctx.font = '10px monospace'
      ctx.fillStyle = '#ff88ff'
      ctx.fillText('chin', cx + 8, cy - 4)
    }

  }, [landmarks, faceLandmarks, headPose])

  return (
    <div ref={containerRef} style={{ width: '100%', height: '100%', background: '#0d0d0d', borderRadius: 8, overflow: 'hidden' }}>
      <canvas ref={canvasRef} style={{ display: 'block' }} />
    </div>
  )
}
