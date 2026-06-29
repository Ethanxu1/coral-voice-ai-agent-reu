import { usePoseWebSocket } from '../hooks/usePoseWebSocket'
import CameraFeed from '../components/pose/CameraFeed'
import SkeletonCanvas from '../components/pose/SkeletonCanvas'
import HeadPoseDisplay from '../components/pose/HeadPoseDisplay'
import CalibrationPanel from '../components/pose/CalibrationPanel'
import StabilityPanel from '../components/pose/StabilityPanel'

export default function PoseVisualization() {
  const {
    bodyLandmarks,
    faceLandmarks,
    headPose,
    calibrationStatus,
    stabilityStatus,
    isConnected,
    trackingLost,
    startCalibration,
    resetCalibration,
    captureStablePosition,
    continueLive,
  } = usePoseWebSocket()

  return (
    <div style={{
      minHeight: '100vh',
      background: '#111',
      color: '#eee',
      fontFamily: 'system-ui, sans-serif',
      padding: 16,
      boxSizing: 'border-box',
    }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <a href="/" style={{ color: '#888', fontSize: 13, textDecoration: 'none' }}>← Back</a>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 600 }}>Pose Tracking</h2>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {trackingLost && (
            <span style={{ fontSize: 12, color: '#f90', background: '#2a1a00', padding: '2px 8px', borderRadius: 4 }}>
              Tracking lost
            </span>
          )}
          <div style={{
            width: 8, height: 8, borderRadius: '50%',
            background: isConnected ? '#0f0' : '#f00',
          }} />
          <span style={{ fontSize: 12, color: '#888' }}>
            {isConnected ? 'Connected' : 'Disconnected'}
          </span>
        </div>
      </div>

      {/* Main layout */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
        {/* Camera feed */}
        <div>
          <div style={{ fontSize: 12, color: '#666', marginBottom: 6 }}>Camera (with overlay)</div>
          <div style={{ aspectRatio: '4/3', background: '#111', borderRadius: 8, overflow: 'hidden' }}>
            <CameraFeed />
          </div>
        </div>

        {/* Skeleton canvas */}
        <div>
          <div style={{ fontSize: 12, color: '#666', marginBottom: 6 }}>3D Skeleton — drag to rotate, scroll to zoom</div>
          <div style={{ aspectRatio: '4/3' }}>
            <SkeletonCanvas
              landmarks={bodyLandmarks}
              faceLandmarks={faceLandmarks}
              headPose={headPose}
            />
          </div>
        </div>
      </div>

      {/* Controls row */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16 }}>
        <CalibrationPanel
          status={calibrationStatus}
          isConnected={isConnected}
          onStart={startCalibration}
          onReset={resetCalibration}
        />
        <StabilityPanel
          status={stabilityStatus}
          isConnected={isConnected}
          onCapture={captureStablePosition}
          onContinue={continueLive}
        />
        <HeadPoseDisplay headPose={headPose} />
      </div>
    </div>
  )
}
