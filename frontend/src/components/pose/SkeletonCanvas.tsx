import { useMemo } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { OrbitControls, Line } from '@react-three/drei'
import * as THREE from 'three'
import type { Landmark, FaceLandmark, HeadPose } from '../../types/pose'

// Upper-body only connections (both endpoints ≤ 24)
const POSE_CONNECTIONS: [number, number][] = [
  [0,1],[1,2],[2,3],[3,7],[0,4],[4,5],[5,6],[6,8],
  [9,10],[11,12],[11,13],[13,15],[15,17],[15,19],[15,21],[17,19],
  [12,14],[14,16],[16,18],[16,20],[16,22],[18,20],
  [11,23],[12,24],[23,24],
]

const UPPER_BODY_MAX = 24
const SPECIAL_INDICES = new Set([0])

function lmToVec3(lm: Landmark): THREE.Vector3 {
  return new THREE.Vector3(
    (lm.x - 0.5) * 2,
    -(lm.y - 0.5) * 2,
    -lm.z * 1.5,
  )
}

function visColor(v: number): string {
  if (v > 0.8) return '#00ff88'
  if (v > 0.4) return '#ffcc00'
  return '#ff4444'
}

function CoordinateAxes() {
  return (
    <>
      {/* X = red, Y = green, Z = blue — anchored at bottom-left of skeleton */}
      <group position={[-1.1, -0.6, 0]}>
        <Line points={[[0,0,0],[0.3,0,0]]} color="#ff4444" lineWidth={2} />
        <Line points={[[0,0,0],[0,0.3,0]]} color="#44ff88" lineWidth={2} />
        <Line points={[[0,0,0],[0,0,0.3]]} color="#4488ff" lineWidth={2} />
        {/* Axis label spheres at tips */}
        <mesh position={[0.32, 0, 0]}>
          <sphereGeometry args={[0.012, 8, 8]} />
          <meshBasicMaterial color="#ff4444" />
        </mesh>
        <mesh position={[0, 0.32, 0]}>
          <sphereGeometry args={[0.012, 8, 8]} />
          <meshBasicMaterial color="#44ff88" />
        </mesh>
        <mesh position={[0, 0, 0.32]}>
          <sphereGeometry args={[0.012, 8, 8]} />
          <meshBasicMaterial color="#4488ff" />
        </mesh>
      </group>
    </>
  )
}

interface SceneProps {
  landmarks: Landmark[]
  headPose: HeadPose | null
}

function SkeletonScene({ landmarks, headPose }: SceneProps) {
  const yawArrow = useMemo(
    () => new THREE.ArrowHelper(new THREE.Vector3(0, 0, -1), new THREE.Vector3(), 0.25, 0xff3333, 0.06, 0.04),
    [],
  )
  const pitchArrow = useMemo(
    () => new THREE.ArrowHelper(new THREE.Vector3(0, 1, 0), new THREE.Vector3(), 0.25, 0x33ff66, 0.06, 0.04),
    [],
  )

  const positions = useMemo(
    () => landmarks.slice(0, UPPER_BODY_MAX + 1).map(lmToVec3),
    [landmarks],
  )

  useFrame(() => {
    if (!positions[0]) return
    const origin = positions[0]
    yawArrow.position.copy(origin)
    pitchArrow.position.copy(origin)

    if (headPose) {
      const yawRad = (headPose.yaw * Math.PI) / 180
      yawArrow.setDirection(new THREE.Vector3(Math.sin(yawRad), 0, -Math.cos(yawRad)).normalize())
      const pitchRad = (headPose.pitch * Math.PI) / 180
      pitchArrow.setDirection(new THREE.Vector3(0, Math.sin(-pitchRad), -Math.cos(pitchRad)).normalize())
    }
  })

  if (!positions.length) return null

  return (
    <>
      {/* Bones */}
      {POSE_CONNECTIONS.map(([a, b], i) => {
        const la = landmarks[a]
        const lb = landmarks[b]
        if (!la || !lb || la.visibility < 0.2 || lb.visibility < 0.2) return null
        const avg = (la.visibility + lb.visibility) / 2
        return (
          <Line
            key={i}
            points={[positions[a], positions[b]]}
            color="#78b4ff"
            lineWidth={1.5}
            transparent
            opacity={Math.max(0.3, avg * 0.8)}
          />
        )
      })}

      {/* Joints */}
      {positions.map((pos, i) => {
        const lm = landmarks[i]
        if (!lm || lm.visibility < 0.2) return null
        const isSpecial = SPECIAL_INDICES.has(i)
        return (
          <mesh key={i} position={pos}>
            <sphereGeometry args={[isSpecial ? 0.022 : 0.013, 10, 10]} />
            <meshStandardMaterial
              color={isSpecial ? '#ff00ff' : visColor(lm.visibility)}
              emissive={isSpecial ? '#cc00cc' : '#000000'}
              emissiveIntensity={isSpecial ? 0.3 : 0}
            />
          </mesh>
        )
      })}

      {/* Head orientation arrows */}
      {headPose && <primitive object={yawArrow} />}
      {headPose && <primitive object={pitchArrow} />}

      <CoordinateAxes />
    </>
  )
}

interface Props {
  landmarks: Landmark[]
  faceLandmarks: FaceLandmark[]
  headPose: HeadPose | null
}

export default function SkeletonCanvas({ landmarks, headPose }: Props) {
  return (
    <Canvas
      camera={{ position: [0, 0.1, 4.5], fov: 45 }}
      dpr={1}
      style={{ background: '#0d0d0d', borderRadius: 8, width: '100%', height: '100%' }}
    >
      <ambientLight intensity={0.9} />
      <pointLight position={[2, 3, 3]} intensity={0.5} />
      <OrbitControls enableDamping dampingFactor={0.1} makeDefault />
      <SkeletonScene landmarks={landmarks} headPose={headPose} />
    </Canvas>
  )
}
