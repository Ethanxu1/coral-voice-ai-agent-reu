// The block-coding area: a Blockly workspace with the dance blocks on a shelf
// down its left side and the start block already placed.

import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react'
import * as Blockly from 'blockly/core'
import * as En from 'blockly/msg/en'
import { START_BLOCK, danceTheme, defineDanceBlocks, readProgram, toolbox, type Step } from './blocks'

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
}

const DanceWorkspace = forwardRef<DanceWorkspaceHandle, Props>(function DanceWorkspace({ locked, onChange }, ref) {
  const hostRef = useRef<HTMLDivElement>(null)
  const workspaceRef = useRef<Blockly.WorkspaceSvg | null>(null)
  const onChangeRef = useRef(onChange)
  onChangeRef.current = onChange

  useEffect(() => {
    defineDanceBlocks()
    const host = hostRef.current!
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
    return () => {
      resize.disconnect()
      workspace.dispose()
      workspaceRef.current = null
    }
  }, [])

  useEffect(() => {
    workspaceRef.current?.setIsReadOnly(locked)
  }, [locked])

  useImperativeHandle(ref, () => ({
    highlight: (blockId) => workspaceRef.current?.highlightBlock(blockId),
  }), [])

  return <div className={`dance-workspace ${locked ? 'locked' : ''}`} ref={hostRef} />
})

export default DanceWorkspace
