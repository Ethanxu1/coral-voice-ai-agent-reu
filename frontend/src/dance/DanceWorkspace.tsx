// The block-coding area: a Blockly workspace with the dance blocks on a shelf
// down its left side and the start block already placed.

import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react'
import * as Blockly from 'blockly/core'
import * as En from 'blockly/msg/en'
import { START_BLOCK, blockPose, danceTheme, defineDanceBlocks, readProgram, toolbox, type Step } from './blocks'
import type { PoseHover } from './PosePreview'
import { loadPoseIcons } from './skeleton'

Blockly.setLocale(En as unknown as Record<string, string>)

export interface DanceWorkspaceHandle {
  /** Light up the block that is playing now (null clears it). */
  highlight: (blockId: string | null) => void
}

interface Props {
  /** While locked (the dance is playing) blocks can't be moved or edited. */
  locked: boolean
  /** Called with the program whenever the blocks change. */
  onChange: (steps: Step[]) => void
  /** Called when the pointer goes onto a move block's stick figure (null when it leaves). */
  onPoseHover: (hover: PoseHover | null) => void
}

/**
 * The move whose stick figure `target` is part of, on the workspace or the
 * shelf. Its rect spans from the icon to the block's right edge, so the popup
 * sits beside the block instead of over its label.
 */
function hoveredPose(workspace: Blockly.WorkspaceSvg, target: EventTarget | null): PoseHover | null {
  const icon = target instanceof Element ? target.closest('.blocklyImageField') : null
  const group = icon?.closest('[data-id]')
  const id = group?.getAttribute('data-id')
  if (!icon || !group || !id) return null
  const block = workspace.getBlockById(id) ?? workspace.getFlyout()?.getWorkspace().getBlockById(id)
  const pose = block && blockPose(block)
  if (!pose) return null
  const at = icon.getBoundingClientRect()
  // The block's own outline (its group also holds the blocks stacked under it).
  const right = (group.querySelector(':scope > .blocklyPath') ?? icon).getBoundingClientRect().right
  return { pose, rect: new DOMRect(at.x, at.y, right - at.x, at.height) }
}

const DanceWorkspace = forwardRef<DanceWorkspaceHandle, Props>(function DanceWorkspace({ locked, onChange, onPoseHover }, ref) {
  const hostRef = useRef<HTMLDivElement>(null)
  const workspaceRef = useRef<Blockly.WorkspaceSvg | null>(null)
  const onChangeRef = useRef(onChange)
  onChangeRef.current = onChange
  const onPoseHoverRef = useRef(onPoseHover)
  onPoseHoverRef.current = onPoseHover

  useEffect(() => {
    let disposed = false
    let cleanup = () => {}
    // The block icons are drawn by the server, so they're fetched before any block is made.
    loadPoseIcons().then(() => {
      if (!disposed) cleanup = createWorkspace(hostRef.current!)
    })
    return () => {
      disposed = true
      cleanup()
    }
  }, [])

  function createWorkspace(host: HTMLDivElement): () => void {
    defineDanceBlocks()
    const workspace = Blockly.inject(host, {
      toolbox: toolbox(),
      theme: danceTheme(),
      renderer: 'zelos',
      trashcan: true,
      sounds: false,
      zoom: { controls: true, startScale: 0.9 },
      move: { scrollbars: true, drag: true, wheel: true },
    })
    workspaceRef.current = workspace
    Blockly.serialization.blocks.append({ type: START_BLOCK, x: 30, y: 30, deletable: false }, workspace)
    workspace.addChangeListener(Blockly.Events.disableOrphans)
    workspace.addChangeListener((e) => {
      if (!e.isUiEvent) onChangeRef.current(readProgram(workspace))
    })

    const resize = new ResizeObserver(() => Blockly.svgResize(workspace))
    resize.observe(host)

    const hover = (e: PointerEvent) => onPoseHoverRef.current(hoveredPose(workspace, e.target))
    const unhover = () => onPoseHoverRef.current(null)
    host.addEventListener('pointerover', hover)
    host.addEventListener('pointerleave', unhover)
    host.addEventListener('pointerdown', unhover)
    return () => {
      host.removeEventListener('pointerover', hover)
      host.removeEventListener('pointerleave', unhover)
      host.removeEventListener('pointerdown', unhover)
      resize.disconnect()
      workspace.dispose()
      workspaceRef.current = null
      unhover()
    }
  }

  useEffect(() => {
    workspaceRef.current?.setIsReadOnly(locked)
  }, [locked])

  useImperativeHandle(ref, () => ({
    highlight: (blockId) => workspaceRef.current?.highlightBlock(blockId),
  }), [])

  return <div className={`dance-workspace ${locked ? 'locked' : ''}`} ref={hostRef} />
})

export default DanceWorkspace
