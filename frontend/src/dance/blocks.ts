// The Dance Game's Blockly blocks, and reading the workspace back as a program.
//
// Blockly owns dragging, snapping, nesting and the toolbox. This file only says
// what the blocks look like and turns the stack under the start block into
// Steps that sequencePlayer.ts walks. Only blocks connected under the start
// block play; Blockly greys out loose ones (Events.disableOrphans) so a child
// can see which.

import * as Blockly from 'blockly/core'
import { DANCE_POSES, SPEED_LABEL, type DancePoseId, type DanceSpeed } from './poses'

export const START_BLOCK = 'dance_start'
const REPEAT_BLOCK = 'dance_repeat'
const poseBlockType = (id: DancePoseId) => `dance_pose_${id}`
const POSE_BY_BLOCK_TYPE = new Map(DANCE_POSES.map((p) => [poseBlockType(p.id), p.id]))

/** One step of a dance program. `blockId` is the Blockly block it came from, for highlighting. */
export type Step =
  | { kind: 'pose'; blockId: string; pose: DancePoseId; speed: DanceSpeed }
  | { kind: 'repeat'; blockId: string; times: number; body: Step[] }

const MAX_REPEAT = 20

let defined = false

/** Register the dance block types with Blockly (once). */
export function defineDanceBlocks(): void {
  if (defined) return
  defined = true
  const speedOptions = Object.entries(SPEED_LABEL).map(([value, text]) => [text, value])
  Blockly.common.defineBlocksWithJsonArray([
    { type: START_BLOCK, message0: 'when ▶ Dance! is pressed', style: 'start_blocks', nextStatement: null },
    {
      type: REPEAT_BLOCK,
      message0: 'repeat %1 times',
      args0: [{ type: 'field_number', name: 'TIMES', value: 2, min: 1, max: MAX_REPEAT, precision: 1 }],
      message1: '%1',
      args1: [{ type: 'input_statement', name: 'DO' }],
      style: 'loop_blocks',
      previousStatement: null,
      nextStatement: null,
    },
    ...DANCE_POSES.map((p) => ({
      type: poseBlockType(p.id),
      message0: `${p.emoji} ${p.label} %1`,
      args0: [{ type: 'field_dropdown', name: 'SPEED', options: speedOptions }],
      style: 'move_blocks',
      previousStatement: null,
      nextStatement: null,
    })),
  ])
}

/** A palette colour from src/theme/palette.css (Blockly needs real colour values, not var()). */
const pal = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(`--pal-${name}`).trim()

/** CORAL's palette as a Blockly theme: moves in coral, loops in teal, the start block in navy. */
export function danceTheme(): Blockly.Theme {
  return Blockly.Theme.defineTheme('coral-dance', {
    name: 'coral-dance',
    base: Blockly.Themes.Zelos,
    blockStyles: {
      start_blocks: { colourPrimary: pal('navy'), colourSecondary: pal('navy-light'), colourTertiary: pal('navy-deep'), hat: 'cap' },
      loop_blocks: { colourPrimary: pal('teal'), colourSecondary: pal('teal-pale'), colourTertiary: pal('navy') },
      move_blocks: { colourPrimary: pal('coral'), colourSecondary: pal('pink'), colourTertiary: pal('coral-deep') },
    },
    componentStyles: {
      workspaceBackgroundColour: pal('white'),
      flyoutBackgroundColour: pal('sand-light'),
      flyoutOpacity: 1,
      scrollbarColour: pal('navy-pale'),
      insertionMarkerColour: pal('navy'),
      selectedGlowColour: pal('gold'),
    },
    fontStyle: { family: "'Fredoka', 'Nunito', sans-serif", weight: '600', size: 15 },
  })
}

/** The always-open block shelf: the loop, then every move at normal speed. */
export const TOOLBOX: Blockly.utils.toolbox.ToolboxInfo = {
  kind: 'flyoutToolbox',
  contents: [
    { kind: 'label', text: 'Loops' },
    { kind: 'block', type: REPEAT_BLOCK },
    { kind: 'label', text: 'Moves' },
    ...DANCE_POSES.map((p) => ({ kind: 'block', type: poseBlockType(p.id), fields: { SPEED: 'normal' } })),
  ],
}

/** Steps for a stack of blocks starting at `first`, skipping any a child disabled. */
function readStack(first: Blockly.Block | null): Step[] {
  const steps: Step[] = []
  for (let b = first; b; b = b.getNextBlock()) {
    if (!b.isEnabled()) continue
    if (b.type === REPEAT_BLOCK) {
      steps.push({ kind: 'repeat', blockId: b.id, times: Number(b.getFieldValue('TIMES')), body: readStack(b.getInputTargetBlock('DO')) })
      continue
    }
    const pose = POSE_BY_BLOCK_TYPE.get(b.type)
    if (pose) steps.push({ kind: 'pose', blockId: b.id, pose, speed: b.getFieldValue('SPEED') as DanceSpeed })
  }
  return steps
}

/** The program: every step snapped under the start block. */
export function readProgram(workspace: Blockly.Workspace): Step[] {
  const start = workspace.getBlocksByType(START_BLOCK)[0]
  return readStack(start?.getNextBlock() ?? null)
}

/** True if the program has at least one move to play (a repeat with nothing inside doesn't count). */
export function hasMoves(steps: Step[]): boolean {
  return steps.some((s) => s.kind === 'pose' || hasMoves(s.body))
}
