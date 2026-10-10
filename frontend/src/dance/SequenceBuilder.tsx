// Right panel: the block-coding canvas the student is building.
//
// Blocks are dragged with native HTML5 drag-and-drop (no library is
// installed in this project). Each block row is both a drag source (grab it
// to move it) and a drop target (hovering it previews "insert before this
// row" by rendering a live indicator bar, which pushes the surrounding rows
// apart via ordinary flex layout — no manual DOM measuring needed). Each
// list also has a container-level fallback drop target, covering the empty
// space below the last row, so "move to the end of this list" is always a
// real, visible, reachable drop target instead of relying on a block
// happening to already sit next to where you want it.
//
// A Repeat block additionally renders its own nested BlockList for its body,
// so blocks can be dropped inside a loop as well as between top-level
// blocks. Every handler calls stopPropagation so a drop on an inner, nested
// list never also fires an outer list's handler, and the hover indicator
// only ever belongs to the single innermost list actually under the pointer.

import { useCallback, useRef, useState, type DragEvent, type ReactNode } from 'react'
import { DANCE_POSE_BY_ID, SPEED_LABEL } from './poses'
import type { Block, PoseBlockT, RepeatBlockT } from './blocks'

/** Which list is currently being hovered during a drag, and at which slot. */
interface DragOver {
  parentUid: string | null
  index: number
}

interface ListProps {
  blocks: Block[]
  parentUid: string | null
  isPlaying: boolean
  activeUid: string | null
  dragOver: DragOver | null
  draggingUid: string | null
  onHover: (parentUid: string | null, index: number) => void
  onDragStart: (uid: string) => void
  onDragEnd: () => void
  onDropBefore: (sourceUid: string, destParentUid: string | null, beforeUid: string | null) => void
  onRemove: (uid: string) => void
  onCycleSpeed: (uid: string) => void
  onRepeatCountChange: (uid: string, n: number) => void
}

function PoseBlockRow({
  block,
  isPlaying,
  onRemove,
  onCycleSpeed,
}: {
  block: PoseBlockT
  isPlaying: boolean
  onRemove: () => void
  onCycleSpeed: () => void
}) {
  const pose = DANCE_POSE_BY_ID[block.poseId]
  return (
    <>
      {!isPlaying && <span className="dance-chip-drag-handle">⠿</span>}
      <span className="dance-chip-emoji">{pose.emoji}</span>
      <span className="dance-chip-label">{pose.label}</span>
      <button className="dance-chip-speed" disabled={isPlaying} onClick={onCycleSpeed}>
        {SPEED_LABEL[block.speed]}
      </button>
      {!isPlaying && (
        <button className="dance-chip-remove" onClick={onRemove} aria-label="Remove">
          ×
        </button>
      )}
    </>
  )
}

function RepeatBlockRow({
  block,
  isPlaying,
  onRemove,
  onCountChange,
  children,
}: {
  block: RepeatBlockT
  isPlaying: boolean
  onRemove: () => void
  onCountChange: (n: number) => void
  children: ReactNode
}) {
  return (
    <div className="dance-repeat-block">
      <div className="dance-repeat-header">
        {!isPlaying && <span className="dance-chip-drag-handle">⠿</span>}
        <span className="dance-repeat-label">🔁 Repeat</span>
        <input
          type="number"
          min={1}
          max={20}
          value={block.count}
          disabled={isPlaying}
          draggable={false}
          onMouseDown={(e) => e.stopPropagation()}
          onChange={(e) => onCountChange(Math.max(1, Math.min(20, Number(e.target.value) || 1)))}
        />
        <span className="dance-repeat-label">times</span>
        {!isPlaying && (
          <button className="dance-chip-remove" onClick={onRemove} aria-label="Remove">
            ×
          </button>
        )}
      </div>
      <div className="dance-repeat-body">{children}</div>
    </div>
  )
}

function BlockList({
  blocks,
  parentUid,
  isPlaying,
  activeUid,
  dragOver,
  draggingUid,
  onHover,
  onDragStart,
  onDragEnd,
  onDropBefore,
  onRemove,
  onCycleSpeed,
  onRepeatCountChange,
}: ListProps) {
  const isHoveredList = !isPlaying && dragOver?.parentUid === parentUid

  // Shared by every drop target in this list (rows, the indicator itself,
  // and the container fallback) so hovering any of them reports the same
  // slot consistently — see the indicator note above for why this matters.
  function dropHandlers(hoverIndex: number, beforeUid: string | null) {
    return {
      onDragOver: (e: DragEvent) => {
        if (isPlaying) return
        e.preventDefault()
        e.stopPropagation()
        onHover(parentUid, hoverIndex)
      },
      onDrop: (e: DragEvent) => {
        if (isPlaying) return
        e.preventDefault()
        e.stopPropagation()
        const sourceUid = e.dataTransfer.getData('text/plain')
        if (sourceUid) onDropBefore(sourceUid, parentUid, beforeUid)
        onDragEnd()
      },
    }
  }

  const rows: ReactNode[] = []
  blocks.forEach((block, i) => {
    if (isHoveredList && dragOver!.index === i) {
      // The indicator is itself a drop target reporting the same slot it
      // displays. Without this, the moment the pointer reaches the gap it
      // just opened, the event falls through to the list's own fallback
      // (which targets the end of the list), snapping the indicator away
      // and closing the gap — which puts the pointer back over a row,
      // reopening the same gap, forever. That loop is what read as "glitchy."
      rows.push(<div key={`indicator-${i}`} className="dance-drop-indicator" {...dropHandlers(i, block.uid)} />)
    }
    rows.push(
      <div
        key={block.uid}
        className={block.type === 'pose' ? `dance-chip${block.uid === activeUid ? ' active' : ''}` : 'dance-block-wrap'}
        style={draggingUid === block.uid ? { opacity: 0.35 } : undefined}
        draggable={!isPlaying}
        onDragStart={(e: DragEvent) => {
          if (isPlaying) return
          e.stopPropagation()
          e.dataTransfer.effectAllowed = 'move'
          e.dataTransfer.setData('text/plain', block.uid)
          onDragStart(block.uid)
        }}
        onDragEnd={(e: DragEvent) => {
          e.stopPropagation()
          onDragEnd()
        }}
        {...dropHandlers(i, block.uid)}
      >
        {block.type === 'pose' ? (
          <PoseBlockRow
            block={block}
            isPlaying={isPlaying}
            onRemove={() => onRemove(block.uid)}
            onCycleSpeed={() => onCycleSpeed(block.uid)}
          />
        ) : (
          <RepeatBlockRow
            block={block}
            isPlaying={isPlaying}
            onRemove={() => onRemove(block.uid)}
            onCountChange={(n) => onRepeatCountChange(block.uid, n)}
          >
            <BlockList
              blocks={block.children}
              parentUid={block.uid}
              isPlaying={isPlaying}
              activeUid={activeUid}
              dragOver={dragOver}
              draggingUid={draggingUid}
              onHover={onHover}
              onDragStart={onDragStart}
              onDragEnd={onDragEnd}
              onDropBefore={onDropBefore}
              onRemove={onRemove}
              onCycleSpeed={onCycleSpeed}
              onRepeatCountChange={onRepeatCountChange}
            />
          </RepeatBlockRow>
        )}
      </div>,
    )
  })
  if (isHoveredList && dragOver!.index >= blocks.length) {
    rows.push(<div key="indicator-end" className="dance-drop-indicator" {...dropHandlers(blocks.length, null)} />)
  }

  return (
    <div className="dance-block-list" {...dropHandlers(blocks.length, null)}>
      {blocks.length === 0 && !isHoveredList && (
        <div className="dance-block-dropzone-empty">
          {parentUid === null ? 'Click poses or Repeat on the left to add them here →' : 'Drop blocks here'}
        </div>
      )}
      {rows}
    </div>
  )
}

export default function SequenceBuilder({
  blocks,
  isPlaying,
  activeUid,
  onDropBefore,
  onRemove,
  onCycleSpeed,
  onRepeatCountChange,
  onPlay,
  onStop,
}: {
  blocks: Block[]
  isPlaying: boolean
  activeUid: string | null
  onDropBefore: (sourceUid: string, destParentUid: string | null, beforeUid: string | null) => void
  onRemove: (uid: string) => void
  onCycleSpeed: (uid: string) => void
  onRepeatCountChange: (uid: string, n: number) => void
  onPlay: () => void
  onStop: () => void
}) {
  const [dragOver, setDragOver] = useState<DragOver | null>(null)
  const [draggingUid, setDraggingUid] = useState<string | null>(null)

  // dragover fires on every pointer tick (far more often than once per
  // frame). Recording only the latest candidate here, and committing it to
  // React state at most once per animation frame, keeps the indicator (and
  // the layout shift it causes) from updating faster than the screen can
  // actually show — which is what made rapid back-and-forth hovering near a
  // row boundary look like flicker rather than a smooth, settled move.
  const pendingHoverRef = useRef<DragOver | null>(null)
  const hoverFrameRef = useRef<number | null>(null)

  const onHover = useCallback((parentUid: string | null, index: number) => {
    pendingHoverRef.current = { parentUid, index }
    if (hoverFrameRef.current !== null) return
    hoverFrameRef.current = requestAnimationFrame(() => {
      hoverFrameRef.current = null
      const next = pendingHoverRef.current
      setDragOver((prev) => (prev?.parentUid === next?.parentUid && prev?.index === next?.index ? prev : next))
    })
  }, [])
  const onDragStart = useCallback((uid: string) => setDraggingUid(uid), [])
  const onDragEndCleanup = useCallback(() => {
    if (hoverFrameRef.current !== null) {
      cancelAnimationFrame(hoverFrameRef.current)
      hoverFrameRef.current = null
    }
    pendingHoverRef.current = null
    setDragOver(null)
    setDraggingUid(null)
  }, [])

  return (
    <div className="dance-builder">
      <div className="dance-panel-title">Make CORAL Dance!</div>

      <div
        className="dance-canvas"
        onDragLeave={(e: DragEvent) => {
          if (!e.currentTarget.contains(e.relatedTarget as Node)) onDragEndCleanup()
        }}
      >
        <BlockList
          blocks={blocks}
          parentUid={null}
          isPlaying={isPlaying}
          activeUid={activeUid}
          dragOver={dragOver}
          draggingUid={draggingUid}
          onHover={onHover}
          onDragStart={onDragStart}
          onDragEnd={onDragEndCleanup}
          onDropBefore={onDropBefore}
          onRemove={onRemove}
          onCycleSpeed={onCycleSpeed}
          onRepeatCountChange={onRepeatCountChange}
        />
      </div>

      <div className="dance-controls">
        {isPlaying ? (
          <button className="dance-play-btn stop" onClick={onStop}>
            Stop
          </button>
        ) : (
          <button className="dance-play-btn" onClick={onPlay} disabled={blocks.length === 0}>
            ▶ Play
          </button>
        )}
      </div>
    </div>
  )
}
