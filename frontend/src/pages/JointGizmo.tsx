// Rotation gizmo for the viewer's manual mode: a single arc ring around a
// joint's axis (the curved-arrow handle from 3D software), placed at the
// joint's world anchor. Dragging the ring reports the signed rotation delta
// since drag start; the parent turns that into an absolute joint angle and
// posts it to the backend, which drives the sim (and thus the meshes).

import { useRef, useState } from 'react'
import { useFrame } from '@react-three/fiber'
import { TransformControls } from '@react-three/drei'
import * as THREE from 'three'

export interface JointFrame {
  name: string
  angle: number // radians
  pos: [number, number, number] // world anchor, MuJoCo Z-up
  axis: [number, number, number] // world rotation axis, MuJoCo Z-up
}

// MuJoCo world is Z-up; the viewer renders Y-up. Matches the robot group's
// -90° X rotation in RobotViewer (y' = z, z' = -y).
function mujocoToThree(v: [number, number, number]): THREE.Vector3 {
  return new THREE.Vector3(v[0], v[2], -v[1])
}

// The dummy's local +Z is aligned with the joint axis, so the controls only
// show the Z ring.
const LOCAL_AXIS = new THREE.Vector3(0, 0, 1)

export default function JointGizmo({
  frame,
  onDragStart,
  onDragDelta,
  onDragEnd,
}: {
  frame: JointFrame
  onDragStart: () => void
  onDragDelta: (deltaRad: number) => void
  onDragEnd: () => void
}) {
  // A plain Object3D (not a JSX ref) avoids TransformControls attach-timing
  // issues — it exists before the controls mount.
  const [dummy] = useState(() => new THREE.Object3D())
  const draggingRef = useRef(false)
  const startQuatRef = useRef(new THREE.Quaternion())
  const axisThreeRef = useRef(new THREE.Vector3(0, 0, 1))

  // Track the streamed joint frame — unless mid-drag, when TransformControls
  // owns the dummy's orientation and the ring must stay under the cursor.
  useFrame(() => {
    if (draggingRef.current) return
    dummy.position.copy(mujocoToThree(frame.pos))
    const axis = mujocoToThree(frame.axis).normalize()
    axisThreeRef.current.copy(axis)
    dummy.quaternion.setFromUnitVectors(LOCAL_AXIS, axis)
  })

  return (
    <>
      <primitive object={dummy} />
      <TransformControls
        object={dummy}
        mode="rotate"
        space="local"
        showX={false}
        showY={false}
        showZ={true}
        size={0.6}
        onMouseDown={() => {
          draggingRef.current = true
          startQuatRef.current.copy(dummy.quaternion)
          onDragStart()
        }}
        onMouseUp={() => {
          if (draggingRef.current) onDragEnd()
          draggingRef.current = false
        }}
        onObjectChange={() => {
          if (!draggingRef.current) return
          // Signed rotation since drag start, projected onto the joint axis:
          // for qRel = current * start⁻¹, dot(qRel.xyz, axis) = sin(θ/2).
          const qRel = dummy.quaternion
            .clone()
            .multiply(startQuatRef.current.clone().invert())
          const axis = axisThreeRef.current
          const s = qRel.x * axis.x + qRel.y * axis.y + qRel.z * axis.z
          onDragDelta(2 * Math.atan2(s, qRel.w))
        }}
      />
    </>
  )
}
