// Stick-figure icons for the Dance Game's move blocks: each pose drawn from the
// robot's own joint positions (POST /pose-design/skeletons), seen from the front.
//
// Blockly shows a block's icon as an <image>, so each figure is an SVG data URI.
// Icons are fetched once, before the workspace is built (loadPoseIcons); a pose
// without one (server unreachable) keeps its emoji, drawn as an SVG too.

import { poseSkeletons, type Skeleton } from '../api/poseDesign'
import { loadCustomPoses } from '../poseDesigner/customPoses'
import { CUSTOM_EMOJI, DANCE_POSES, danceMove } from './poses'

/** The icon's size on a block, in px. */
export const ICON_SIZE = 40

type Point2 = [number, number]

/** Bones, as pairs of skeleton points. The spine and head are added from these. */
const BONES: [string, string][] = [
  ['l_shoulder', 'r_shoulder'], ['l_hip', 'r_hip'],
  ...(['l', 'r'] as const).flatMap((s): [string, string][] => [
    [`${s}_shoulder`, `${s}_elbow`], [`${s}_elbow`, `${s}_hand`],
    [`${s}_hip`, `${s}_knee`], [`${s}_knee`, `${s}_ankle`],
  ]),
]

/** Head radius and how far above the head joint its centre sits, in metres. */
const HEAD_R = 0.03
const HEAD_LIFT = 0.025
/** Drawing scale (px per metre) for the 100 px viewBox, shrunk if a pose doesn't fit. */
const SCALE = 240
const VIEW = 100
const MARGIN = 8

/** Front view: the robot faces the viewer, so its left (+y) is on the right; z is up. */
const front = ([, y, z]: number[]): Point2 => [y, -z]
const mid = (a: Point2, b: Point2): Point2 => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]

/** The SVG markup of one stick figure, in `colour`. */
export function skeletonSvg(skeleton: Skeleton, colour: string): string {
  const p = (name: string) => front(skeleton[name])
  const head = p('head')
  head[1] -= HEAD_LIFT
  const neck = mid(p('l_shoulder'), p('r_shoulder'))
  const lines: [Point2, Point2][] = [[neck, mid(p('l_hip'), p('r_hip'))], ...BONES.map(([a, b]): [Point2, Point2] => [p(a), p(b)])]

  // Fit: centre the figure, and shrink it only if it would spill out of the box.
  const xs = [...lines.flat().map((q) => q[0]), head[0] - HEAD_R, head[0] + HEAD_R]
  const ys = [...lines.flat().map((q) => q[1]), head[1] - HEAD_R]
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)]
  const scale = Math.min(SCALE, (VIEW - 2 * MARGIN) / (x1 - x0), (VIEW - 2 * MARGIN) / (y1 - y0))
  const cx = (x0 + x1) / 2
  const cy = (y0 + y1) / 2
  const at = ([x, y]: Point2) => `${(VIEW / 2 + (x - cx) * scale).toFixed(1)} ${(VIEW / 2 + (y - cy) * scale).toFixed(1)}`
  const [hx, hy] = at(head).split(' ')

  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${VIEW} ${VIEW}">` +
    `<path d="${lines.map(([a, b]) => `M${at(a)}L${at(b)}`).join('')}" stroke="${colour}" stroke-width="9" stroke-linecap="round" stroke-linejoin="round" fill="none"/>` +
    `<circle cx="${hx}" cy="${hy}" r="${(HEAD_R * scale).toFixed(1)}" fill="${colour}"/>` +
    `</svg>`
  )
}

const dataUri = (svg: string) => `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`

const emojiIcon = (emoji: string) =>
  dataUri(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${VIEW} ${VIEW}"><text x="50" y="80" font-size="76" text-anchor="middle">${emoji}</text></svg>`)

/** Pose id -> icon data URI, filled by loadPoseIcons. */
const icons = new Map<string, string>()

/** The icon colour: white, to stand out on the coral move blocks (palette.css). */
const iconColour = () => getComputedStyle(document.documentElement).getPropertyValue('--pal-white').trim() || '#fff'

/** Fetch a stick figure for every preset and Pose Designer pose. Never throws. */
export async function loadPoseIcons(): Promise<void> {
  const poses: Record<string, Record<string, number>> = {}
  for (const p of DANCE_POSES) poses[p.id] = p.robotPulses
  for (const p of loadCustomPoses()) poses[p.id] = p.pulses
  try {
    const skeletons = await poseSkeletons(poses)
    const colour = iconColour()
    for (const [id, skeleton] of Object.entries(skeletons)) icons.set(id, dataUri(skeletonSvg(skeleton, colour)))
  } catch (e) {
    console.warn('pose icons unavailable, using emoji', e)
  }
}

/** The icon for a pose id: its stick figure, else its emoji. */
export function poseIcon(id: string): string {
  return icons.get(id) ?? emojiIcon(danceMove(id)?.emoji ?? CUSTOM_EMOJI)
}
