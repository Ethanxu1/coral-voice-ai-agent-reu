import { useEffect, useState, type RefObject } from 'react'

/** Where the beam fans out to: this share of the eye's height is left clear at its top and bottom corners. */
const EDGE_INSET = 0.06

type Point = [number, number]

/**
 * The beam from CORAL's head to its eye panel, so a child sees that the panel
 * is what the robot is looking at. Drawn over `area` from the head (`head`, a
 * share of the `robot` canvas, reported by RobotViewer) to the left edge of `eye`.
 * Re-measured whenever any of them resizes.
 */
export default function CoralBeam({
  area,
  robot,
  eye,
  head,
}: {
  area: RefObject<HTMLElement>
  robot: RefObject<HTMLElement>
  eye: RefObject<HTMLElement>
  head: Point | null
}) {
  const [shape, setShape] = useState<{ from: Point; top: Point; bottom: Point } | null>(null)

  useEffect(() => {
    const measure = () => {
      const a = area.current?.getBoundingClientRect()
      const r = robot.current?.getBoundingClientRect()
      const e = eye.current?.getBoundingClientRect()
      if (!a || !r || !e || !head) return setShape(null)
      const inset = e.height * EDGE_INSET
      setShape({
        from: [r.left - a.left + head[0] * r.width, r.top - a.top + head[1] * r.height],
        top: [e.left - a.left + 1, e.top - a.top + inset],
        bottom: [e.left - a.left + 1, e.bottom - a.top - inset],
      })
    }
    measure()
    const observer = new ResizeObserver(measure)
    for (const el of [area.current, robot.current, eye.current]) if (el) observer.observe(el)
    // The eye opens with a short scale animation; measure again once it has settled.
    const settle = setTimeout(measure, 700)
    return () => {
      observer.disconnect()
      clearTimeout(settle)
    }
  }, [area, robot, eye, head])

  if (!shape) return null
  const { from, top, bottom } = shape
  return (
    <svg className="coral-beam" aria-hidden>
      <defs>
        <linearGradient id="coral-beam-fade" gradientUnits="userSpaceOnUse" x1={from[0]} y1={from[1]} x2={top[0]} y2={from[1]}>
          <stop offset="0" stopColor="#FF7A59" stopOpacity="0.7" />
          <stop offset="1" stopColor="#FF7A59" stopOpacity="0.18" />
        </linearGradient>
      </defs>
      <polygon points={[from, top, bottom].map((p) => p.join(',')).join(' ')} fill="url(#coral-beam-fade)" />
    </svg>
  )
}
