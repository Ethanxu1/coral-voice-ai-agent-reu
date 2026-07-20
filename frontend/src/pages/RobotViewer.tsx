// In-browser MuJoCo viewer: a puppet that mirrors the server's simulation.
//
// The Python server runs the physics and streams every robot link's world pose
// over a WebSocket (see server.py /ws/sim + mujoco_sim.get_geom_poses). This
// component loads the same STL meshes once, then each frame moves them to the
// streamed poses. No physics runs here — it can never drift from the real sim.

import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Canvas, useFrame } from '@react-three/fiber'
import { OrbitControls, Grid } from '@react-three/drei'
import * as THREE from 'three'
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js'
import { SIM_WS } from '../demo/config'
import JointGizmo, { JointFrame } from './JointGizmo'

interface GeomInfo {
  mesh: string
  rgba: [number, number, number, number]
  // MuJoCo's recentering offset for this mesh (see get_render_geom_info).
  mesh_pos: [number, number, number]
  mesh_quat: [number, number, number, number] // wxyz
  // Short joint name of the geom's owning body, null for joint-less bodies
  // (torso). Used by manual mode to map hovered/clicked meshes to joints.
  joint: string | null
}

// Static per-joint metadata from the init frame (see get_joint_metadata).
interface JointStaticInfo {
  min: number // radians
  max: number
  geom_indices: number[]
}

type ViewerMode = 'auto' | 'manual'

interface HoverInfo {
  joint: string
  x: number // viewport px, for the tooltip
  y: number
}

// Bake MuJoCo's mesh recentering into a raw STL so it lines up with the streamed
// geom pose: v_proc = R(mesh_quat)^T @ (v_raw - mesh_pos). Without this, every
// link renders offset by its own centroid and the robot looks exploded.
function bakeMeshOffset(geo: THREE.BufferGeometry, g: GeomInfo) {
  const [w, x, y, z] = g.mesh_quat // MuJoCo wxyz -> three.js (x, y, z, w)
  const rotInv = new THREE.Matrix4().makeRotationFromQuaternion(new THREE.Quaternion(x, y, z, w)).invert()
  const transNeg = new THREE.Matrix4().makeTranslation(-g.mesh_pos[0], -g.mesh_pos[1], -g.mesh_pos[2])
  geo.applyMatrix4(rotInv.multiply(transNeg))
}

// Wire layout per geom: [x, y, z, qw, qx, qy, qz] (see get_geom_poses).
const FLOATS_PER_GEOM = 7
// Trailing [x, y, z] after all geoms: whole-robot center of mass (subtree_com[0]).
const COM_FLOATS = 3

// How far the ground-projected COM can drift from the world origin before we
// flag it as a balance risk. This only works because the robot's stance never
// translates in this sim (no walking) — world origin ≈ center of its support
// polygon. Thresholds are placeholders (no measured foot-polygon geometry).
const COM_WARN_M = 0.03
const COM_DANGER_M = 0.06

// The server sends mesh_url as a root-relative path (/assets/...), which would
// otherwise resolve against the Vite dev origin (5173) and hand STLLoader the
// SPA's index.html. Resolve it against the backend origin instead, derived from
// the sim WebSocket URL (ws://host:8000/ws/sim -> http://host:8000).
const BACKEND_ORIGIN = (() => {
  const u = new URL(SIM_WS)
  return `${u.protocol === 'wss:' ? 'https:' : 'http:'}//${u.host}`
})()

/** Moves the pre-loaded meshes to the latest streamed poses every frame. */
function RobotMeshes({
  geoms,
  geometries,
  posesRef,
  interactive,
  hoveredJoint,
  selectedJoint,
  onHoverJoint,
  onSelectJoint,
}: {
  geoms: GeomInfo[]
  geometries: THREE.BufferGeometry[]
  posesRef: React.MutableRefObject<Float32Array | null>
  // Manual mode: raycast hover/click against meshes to pick joints.
  interactive: boolean
  hoveredJoint: string | null
  selectedJoint: string | null
  onHoverJoint: (joint: string | null, x: number, y: number) => void
  onSelectJoint: (joint: string) => void
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
      // MuJoCo packs quaternions [w, x, y, z]; three.js wants (x, y, z, w).
      m.quaternion.set(poses[o + 4], poses[o + 5], poses[o + 6], poses[o + 3])
    }
  })

  return (
    // MuJoCo world is Z-up; three.js is Y-up. Rotate the whole robot -90° about
    // X so "up" in the sim becomes "up" on screen.
    <group rotation={[-Math.PI / 2, 0, 0]}>
      {geometries.map((geo, i) => {
        const joint = geoms[i].joint
        const pickable = interactive && joint != null
        const highlight =
          joint != null && joint === selectedJoint
            ? '#f59e0b' // amber: selected joint's link
            : joint != null && joint === hoveredJoint
              ? '#38bdf8' // blue: hovered link
              : '#000000'
        return (
          <mesh
            key={i}
            ref={(el) => (meshRefs.current[i] = el)}
            geometry={geo}
            onPointerMove={
              pickable
                ? (e) => {
                    e.stopPropagation()
                    onHoverJoint(joint, e.nativeEvent.clientX, e.nativeEvent.clientY)
                  }
                : undefined
            }
            onPointerOut={pickable ? () => onHoverJoint(null, 0, 0) : undefined}
            onClick={
              pickable
                ? (e) => {
                    e.stopPropagation()
                    onSelectJoint(joint)
                  }
                : undefined
            }
          >
            <meshStandardMaterial
              color={new THREE.Color(geoms[i].rgba[0], geoms[i].rgba[1], geoms[i].rgba[2])}
              metalness={0.15}
              roughness={0.6}
              emissive={new THREE.Color(highlight)}
              emissiveIntensity={highlight === '#000000' ? 0 : 0.5}
            />
          </mesh>
        )
      })}
    </group>
  )
}

export default function RobotViewer({
  embedded = false,
  forcedMode,
}: {
  embedded?: boolean
  forcedMode?: 'auto' | 'manual'
} = {}) {
  const [geoms, setGeoms] = useState<GeomInfo[]>([])
  const [geometries, setGeometries] = useState<THREE.BufferGeometry[]>([])
  const [status, setStatus] = useState('connecting…')
  const posesRef = useRef<Float32Array | null>(null)
  // Ground-projected (x, y) distance of the whole-robot COM from the world
  // origin, in meters. Polled off posesRef on a slow timer — no need to
  // re-render at the pose stream's full 30fps for a text readout.
  const [comDeviance, setComDeviance] = useState<number | null>(null)

  // --- Manual mode: hover/click joints, rotate them with a gizmo ---
  const [mode, setMode] = useState<ViewerMode>(forcedMode ?? 'auto')
  const [hovered, setHovered] = useState<HoverInfo | null>(null)
  const [selectedJoint, setSelectedJoint] = useState<string | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  // While dragging the gizmo the cursor may not be over a mesh, but we still
  // want the tooltip to follow it. Track it globally while in manual mode.
  const [pointerPos, setPointerPos] = useState<{ x: number; y: number }>({ x: 0, y: 0 })
  // Static limits/geom association from the init frame.
  const [jointsStatic, setJointsStatic] = useState<Record<string, JointStaticInfo>>({})
  // Live per-joint angle/anchor/axis, pushed by the server at ~5 Hz. A state
  // copy drives the tooltip/gizmo props; a ref mirror lets drag callbacks read
  // the latest angle without stale closures.
  const [jointFrames, setJointFrames] = useState<Record<string, JointFrame>>({})
  const jointFramesRef = useRef<Record<string, JointFrame>>({})
  // Joint angle at the moment the current gizmo drag started.
  const dragStartAngleRef = useRef(0)
  // Throttle for POST /joint/set: one request in flight, latest angle wins.
  const dragSendRef = useRef<{ inflight: boolean; pending: number | null }>({
    inflight: false,
    pending: null,
  })

  const sendJointAngle = (name: string, angle: number) => {
    const send = dragSendRef.current
    if (send.inflight) {
      send.pending = angle
      return
    }
    send.inflight = true
    fetch(`${BACKEND_ORIGIN}/joint/set`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, angle }),
    })
      .catch(() => {}) // best-effort; the next drag tick retries
      .finally(() => {
        send.inflight = false
        if (send.pending != null) {
          const next = send.pending
          send.pending = null
          sendJointAngle(name, next)
        }
      })
  }

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
              setJointsStatic(msg.joints ?? {})
              setStatus('streaming')
            } catch (err) {
              setStatus(`mesh load failed: ${err}`)
            }
          } else if (msg.type === 'joints') {
            // Live per-joint angle/anchor/axis at ~5 Hz (manual mode data).
            const frames: Record<string, JointFrame> = {}
            for (const f of msg.joints as JointFrame[]) frames[f.name] = f
            jointFramesRef.current = frames
            setJointFrames(frames)
          } else if (msg.type === 'error') {
            setStatus(`error: ${msg.detail}`)
          }
        } else {
          // Binary pose frame — stash for the render loop to consume.
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

  useEffect(() => {
    if (geometries.length === 0) return
    const comOffset = geometries.length * FLOATS_PER_GEOM
    const id = setInterval(() => {
      const poses = posesRef.current
      if (!poses || poses.length < comOffset + COM_FLOATS) return
      const comX = poses[comOffset]
      const comY = poses[comOffset + 1]
      setComDeviance(Math.hypot(comX, comY))
    }, 150)
    return () => clearInterval(id)
  }, [geometries.length])

  // Track pointer globally in manual mode so the active-joint tooltip can follow
  // the cursor while dragging the gizmo (when the cursor isn't over a mesh).
  useEffect(() => {
    if (mode !== 'manual') return
    const onMove = (e: PointerEvent) => setPointerPos({ x: e.clientX, y: e.clientY })
    window.addEventListener('pointermove', onMove)
    return () => window.removeEventListener('pointermove', onMove)
  }, [mode])

  const comColor =
    comDeviance == null ? '#94a3b8' : comDeviance > COM_DANGER_M ? '#f87171' : comDeviance > COM_WARN_M ? '#fbbf24' : '#4ade80'

  const switchMode = (next: ViewerMode) => {
    if (forcedMode) return
    setMode(next)
    if (next === 'auto') {
      setHovered(null)
      setSelectedJoint(null)
      setIsDragging(false)
    }
  }

  const rad2deg = (r: number) => ((r * 180) / Math.PI).toFixed(1)

  const modeButtonStyle = (active: boolean): React.CSSProperties => ({
    padding: '4px 10px',
    borderRadius: 5,
    border: 'none',
    cursor: 'pointer',
    font: '12px system-ui, sans-serif',
    background: active ? '#3b82f6' : 'transparent',
    color: active ? '#fff' : '#94a3b8',
  })

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
          <Link to="/" style={{ color: '#93c5fd', textDecoration: 'none' }}>
            ← Back
          </Link>
          <span style={{ opacity: 0.7 }}>MuJoCo viewer · {status}</span>
        </div>
      )}

      {!embedded && (
        <div
          style={{
            position: 'absolute',
            zIndex: 1,
            top: 12,
            right: 12,
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '6px 10px',
            borderRadius: 6,
            background: 'rgba(21, 21, 26, 0.7)',
            color: '#cbd5e1',
            font: '12px ui-monospace, Menlo, monospace',
          }}
        >
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: comColor, flexShrink: 0 }} />
          <span>
            CoM Δ from origin:{' '}
            {comDeviance == null ? '—' : `${(comDeviance * 100).toFixed(1)} cm`}
          </span>
        </div>
      )}

      {/* Mode toggle: automatic (agent drives the sim) vs manual (user rotates
          joints with the mouse). Hidden when the parent forces a mode. */}
      {!forcedMode && (
        <div
          style={{
            position: 'absolute',
            zIndex: 2,
            top: 12,
            left: '50%',
            transform: 'translateX(-50%)',
            display: 'flex',
            gap: 4,
            padding: 4,
            borderRadius: 7,
            background: 'rgba(21, 21, 26, 0.7)',
          }}
        >
          <button style={modeButtonStyle(mode === 'auto')} onClick={() => switchMode('auto')}>
            Automatic
          </button>
          <button style={modeButtonStyle(mode === 'manual')} onClick={() => switchMode('manual')}>
            Manual
          </button>
        </div>
      )}

      {/* Manual-mode instruction label for the tutorial playground. */}
      {forcedMode === 'manual' && (
        <div
          style={{
            position: 'absolute',
            zIndex: 2,
            top: 12,
            left: 12,
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '8px 12px',
            borderRadius: 8,
            background: 'rgba(21, 21, 26, 0.75)',
            color: '#e2e8f0',
            font: '13px Nunito, system-ui, sans-serif',
            maxWidth: 280,
          }}
        >
          <span style={{ fontSize: 16 }}>👆</span>
          Click a body part, then drag the ring to move it.
        </div>
      )}

      {/* Manual-mode tooltip: shows the hovered joint normally, and the active
          (selected/dragged) joint's angle when a gizmo is in use. PointerEvents
          disabled so the ring behind it remains interactive. */}
      {mode === 'manual' && (() => {
        const joint = isDragging ? selectedJoint : hovered?.joint ?? selectedJoint
        if (!joint) return null
        const pos = isDragging ? pointerPos : (hovered ?? { x: 0, y: 0 })
        return (
          <div
            style={{
              position: 'fixed',
              left: pos.x + 14,
              top: pos.y + 14,
              zIndex: 3,
              pointerEvents: 'none',
              padding: '6px 10px',
              borderRadius: 6,
              background: 'rgba(21, 21, 26, 0.85)',
              color: '#e2e8f0',
              font: '12px ui-monospace, Menlo, monospace',
              whiteSpace: 'pre',
            }}
          >
            {`${joint}${isDragging ? ' · dragging' : ''}\nangle: ${
              jointFrames[joint] ? rad2deg(jointFrames[joint].angle) : '—'
            }°\nrange: [${
              jointsStatic[joint]
                ? `${rad2deg(jointsStatic[joint].min)}°, ${rad2deg(jointsStatic[joint].max)}°`
                : '—'
            }]`}
          </div>
        )
      })()}

      <Canvas
        camera={{ position: [0.5, 0.35, 0.6], fov: 45, near: 0.01, far: 50 }}
        onPointerMissed={() => {
          if (mode === 'manual') setSelectedJoint(null)
        }}
      >
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
          <RobotMeshes
            geoms={geoms}
            geometries={geometries}
            posesRef={posesRef}
            interactive={mode === 'manual' && selectedJoint == null}
            hoveredJoint={hovered?.joint ?? null}
            selectedJoint={selectedJoint}
            onHoverJoint={(joint, x, y) =>
              setHovered(joint ? { joint, x, y } : null)
            }
            onSelectJoint={setSelectedJoint}
          />
        )}
        {mode === 'manual' && selectedJoint && jointFrames[selectedJoint] && (
          <JointGizmo
            frame={jointFrames[selectedJoint]}
            onDragStart={() => {
              dragStartAngleRef.current =
                jointFramesRef.current[selectedJoint]?.angle ?? 0
              setIsDragging(true)
            }}
            onDragDelta={(delta) =>
              sendJointAngle(selectedJoint, dragStartAngleRef.current + delta)
            }
            onDragEnd={() => {
              setIsDragging(false)
            }}
          />
        )}
        <OrbitControls makeDefault target={[0, 0.15, 0]} />
      </Canvas>
    </div>
  )
}
