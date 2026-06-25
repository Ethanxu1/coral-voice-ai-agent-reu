import { Link } from 'react-router-dom'
import { usePoseWebSocket } from '../hooks/usePoseWebSocket'
import CameraFeed from './pose/CameraFeed'
import SkeletonCanvas from './pose/SkeletonCanvas'

interface Props {
  followActive: boolean
  captureStage: string | null
  onCapturePose: () => void
  onToggleFollow: () => void
}

export default function HomeVisionPanel({
  followActive,
  captureStage,
  onCapturePose,
  onToggleFollow,
}: Props) {
  const {
    bodyLandmarks,
    faceLandmarks,
    headPose,
    stabilityStatus,
    isConnected,
    trackingLost,
  } = usePoseWebSocket()

  const stabilityLabel: Record<string, string> = {
    idle: 'Ready',
    countdown: 'Get ready…',
    collecting: 'Analyzing…',
    frozen: 'Captured',
  }

  const stabilityColor: Record<string, string> = {
    idle: '#888',
    countdown: '#0cf',
    collecting: '#f90',
    frozen: '#0f0',
  }

  return (
    <div className="home-vision-panel panel">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <h3 style={{ margin: 0, fontSize: 15 }}>Vision</h3>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {trackingLost && (
            <span style={{ fontSize: 11, color: '#f90', background: '#2a1a00', padding: '2px 6px', borderRadius: 4 }}>
              Tracking lost
            </span>
          )}
          {followActive && (
            <span style={{ fontSize: 11, color: '#0f0', background: '#0a2a0a', padding: '2px 6px', borderRadius: 4 }}>
              Following
            </span>
          )}
          {captureStage && captureStage !== 'done' && captureStage !== 'error' && (
            <span style={{ fontSize: 11, color: '#0cf', background: '#0a1a2a', padding: '2px 6px', borderRadius: 4 }}>
              Capture: {captureStage}
            </span>
          )}
          <div style={{ width: 8, height: 8, borderRadius: '50%', background: isConnected ? '#0f0' : '#f00' }} />
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 8 }}>
        <div style={{ aspectRatio: '4/3', background: '#111', borderRadius: 6, overflow: 'hidden' }}>
          <CameraFeed />
        </div>
        <div style={{ aspectRatio: '4/3', background: '#111', borderRadius: 6, overflow: 'hidden' }}>
          <SkeletonCanvas
            landmarks={bodyLandmarks}
            faceLandmarks={faceLandmarks}
            headPose={headPose}
          />
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <span style={{ fontSize: 11, color: stabilityColor[stabilityStatus.state] ?? '#888' }}>
          Stability: {stabilityLabel[stabilityStatus.state] ?? stabilityStatus.state}
        </span>
        <Link to="/pose" style={{ fontSize: 11, color: '#888', textDecoration: 'none' }}>
          Detailed view →
        </Link>
      </div>

      <div style={{ display: 'flex', gap: 8 }}>
        <button
          onClick={onToggleFollow}
          disabled={!isConnected}
          style={{
            flex: 1, padding: '6px 12px', borderRadius: 6, border: 'none',
            background: !isConnected ? '#333' : followActive ? '#dc2626' : '#2563eb',
            color: !isConnected ? '#666' : '#fff',
            cursor: !isConnected ? 'default' : 'pointer',
            fontSize: 12, fontWeight: 600,
          }}
        >
          {followActive ? 'Stop Following' : 'Follow Movement'}
        </button>
        <button
          onClick={onCapturePose}
          disabled={!isConnected || stabilityStatus.state !== 'idle'}
          style={{
            flex: 1, padding: '6px 12px', borderRadius: 6, border: 'none',
            background: !isConnected || stabilityStatus.state !== 'idle' ? '#333' : '#16a34a',
            color: !isConnected || stabilityStatus.state !== 'idle' ? '#666' : '#fff',
            cursor: !isConnected || stabilityStatus.state !== 'idle' ? 'default' : 'pointer',
            fontSize: 12, fontWeight: 600,
          }}
        >
          Capture Pose
        </button>
      </div>
    </div>
  )
}
