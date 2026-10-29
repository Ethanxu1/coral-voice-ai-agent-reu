// In-browser MuJoCo viewer: a puppet that mirrors the server's simulation.
//
// The Python server runs the physics and streams every robot link's world pose
// over a WebSocket. This component loads the same STL meshes once, then each
// frame moves them to the streamed poses. No physics runs here.

import { useEffect, useRef, useState } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { ContactShadows, OrbitControls, Grid } from '@react-three/drei'
import * as THREE from 'three'
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js'
import { SIM_WS } from '../config'

interface GeomInfo {
  mesh: string
  rgba: [number, number, number, number]
  mesh_pos: [number, number, number]
  mesh_quat: [number, number, number, number] // wxyz
}

const FLOATS_PER_GEOM = 7

const BACKEND_ORIGIN = (() => {
  const u = new URL(SIM_WS)
  return `${u.protocol === 'wss:' ? 'https:' : 'http:'}//${u.host}`
})()

function bakeMeshOffset(geo: THREE.BufferGeometry, g: GeomInfo) {
  const [w, x, y, z] = g.mesh_quat
  const rotInv = new THREE.Matrix4().makeRotationFromQuaternion(new THREE.Quaternion(x, y, z, w)).invert()
  const transNeg = new THREE.Matrix4().makeTranslation(-g.mesh_pos[0], -g.mesh_pos[1], -g.mesh_pos[2])
  geo.applyMatrix4(rotInv.multiply(transNeg))
}

/**
 * How the viewer looks. `lab` is the plain grey robot on a grid; `stage` is the
 * Rock Paper Scissors character look: CORAL in its own colour, warm light, a
 * soft floor, a transparent background (the page paints the room) and a camera
 * framing the whole robot from the front.
 */
export type ViewerLook = 'lab' | 'stage'

/** CORAL's colours on the stage: its shell, and the darker joints and servos. */
const STAGE_BODY = new THREE.Color('#FF7A59')
const STAGE_JOINT = new THREE.Color('#7A2E3A')
const STAGE_HEAD = new THREE.Color('#FFE3D3')

/** A light head, and hands and feet in the darker tone, so they read against the shell. */
const stageColor = (g: GeomInfo) =>
  g.mesh.startsWith('head_tilt') ? STAGE_HEAD : /gripper|ank/.test(g.mesh) ? STAGE_JOINT : STAGE_BODY

function RobotMeshes({
  geoms,
  geometries,
  posesRef,
  look,
}: {
  geoms: GeomInfo[]
  geometries: THREE.BufferGeometry[]
  posesRef: React.MutableRefObject<Float32Array | null>
  look: ViewerLook
}) {
  const meshRefs = useRef<(THREE.Mesh | null)[]>([])

  useFrame(() => {
    const poses = posesRef.current
    if (!poses) return
    for (let i = 0; i < geometries.length; i++) {
      const m = meshRefs.current[i]
      if (!m) continue
      const o = i * FLOATS_PER_GEOM
      m.position.set(poses[o], poses[o + 1], poses[o + 2])
      // Normalize: under x86 emulation (the Docker backend on Apple silicon) MuJoCo's
      // mju_mat2Quat returns the right rotation with the wrong length, and three.js
      // turns a non-unit quaternion into a scaled, stretched mesh.
      m.quaternion.set(poses[o + 4], poses[o + 5], poses[o + 6], poses[o + 3]).normalize()
    }
  })

  return (
    <group rotation={[-Math.PI / 2, 0, 0]}>
      {geometries.map((geo, i) => (
        <mesh key={i} ref={(el) => (meshRefs.current[i] = el)} geometry={geo}>
          <meshStandardMaterial
            color={
              look === 'stage'
                ? stageColor(geoms[i])
                : new THREE.Color(geoms[i].rgba[0], geoms[i].rgba[1], geoms[i].rgba[2])
            }
            metalness={look === 'stage' ? 0.05 : 0.15}
            roughness={look === 'stage' ? 0.45 : 0.6}
          />
        </mesh>
      ))}
    </group>
  )
}

export default function RobotViewer({ embedded = false, look = 'lab' }: { embedded?: boolean; look?: ViewerLook } = {}) {
  const [geoms, setGeoms] = useState<GeomInfo[]>([])
  const [geometries, setGeometries] = useState<THREE.BufferGeometry[]>([])
  const [status, setStatus] = useState('connecting…')
  const posesRef = useRef<Float32Array | null>(null)

  useEffect(() => {
    let ws: WebSocket | null = null
    let closed = false

    const connect = () => {
      ws = new WebSocket(SIM_WS)
      ws.binaryType = 'arraybuffer'

      ws.onopen = () => setStatus('loading meshes…')

      ws.onmessage = async (ev) => {
        if (typeof ev.data === 'string') {
          const msg = JSON.parse(ev.data)
          if (msg.type === 'init') {
            const loader = new STLLoader()
            const base = BACKEND_ORIGIN + msg.mesh_url
            try {
              const loaded: THREE.BufferGeometry[] = await Promise.all(
                msg.geoms.map(async (g: GeomInfo) => {
                  const geo = await loader.loadAsync(base + g.mesh + '.STL')
                  bakeMeshOffset(geo, g)
                  return geo
                }),
              )
              if (closed) return
              setGeoms(msg.geoms)
              setGeometries(loaded)
              setStatus('streaming')
            } catch (err) {
              setStatus(`mesh load failed: ${err}`)
            }
          } else if (msg.type === 'error') {
            setStatus(`error: ${msg.detail}`)
          }
        } else {
          posesRef.current = new Float32Array(ev.data as ArrayBuffer)
        }
      }

      ws.onclose = () => {
        if (closed) return
        setStatus('reconnecting…')
        setTimeout(connect, 1000)
      }
    }

    connect()
    return () => {
      closed = true
      ws?.close()
    }
  }, [])

  return (
    <div
      style={
        embedded
          ? { position: 'absolute', inset: 0, width: '100%', height: '100%', zIndex: 1 }
          : { position: 'relative', width: '100vw', height: '100vh', background: '#15151a' }
      }
    >
      {!embedded && (
        <div
          style={{
            position: 'absolute',
            zIndex: 1,
            top: 12,
            left: 12,
            display: 'flex',
            gap: 12,
            alignItems: 'center',
            color: '#cbd5e1',
            font: '13px system-ui, sans-serif',
          }}
        >
          <span style={{ opacity: 0.7 }}>MuJoCo viewer · {status}</span>
        </div>
      )}

      {look === 'stage' ? (
        <Canvas camera={{ position: [0.95, 0.25, 0], fov: 38, near: 0.01, far: 50 }} gl={{ alpha: true }}>
          <hemisphereLight args={['#FFF1E0', '#C98B6B', 1.4]} />
          <directionalLight position={[2.5, 2.5, 1]} intensity={2} color="#FFE8D2" />
          <directionalLight position={[-2, 1.5, -1]} intensity={0.5} color="#FFB59E" />
          <ContactShadows position={[0.02, 0.001, 0]} scale={0.8} blur={2.4} opacity={0.35} far={0.5} color="#7A2E3A" />
          {geometries.length > 0 && (
            <RobotMeshes geoms={geoms} geometries={geometries} posesRef={posesRef} look={look} />
          )}
          <OrbitControls makeDefault target={[0.02, 0.22, 0]} enablePan={false} />
        </Canvas>
      ) : (
        <Canvas camera={{ position: [0.5, 0.35, 0.6], fov: 45, near: 0.01, far: 50 }}>
          <ambientLight intensity={0.7} />
          <directionalLight position={[3, 5, 2]} intensity={1.2} />
          <directionalLight position={[-3, 3, -2]} intensity={0.4} />
          <Grid
            args={[4, 4]}
            cellSize={0.1}
            cellThickness={0.6}
            sectionSize={0.5}
            sectionThickness={1}
            infiniteGrid
            fadeDistance={8}
            cellColor="#3a3a44"
            sectionColor="#4f6a8f"
          />
          {geometries.length > 0 && (
            <RobotMeshes geoms={geoms} geometries={geometries} posesRef={posesRef} look={look} />
          )}
          <OrbitControls makeDefault target={[0, 0.15, 0]} />
        </Canvas>
      )}
    </div>
  )
}
