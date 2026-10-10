// Tree data model for the Dance Game's block-coding sequence builder.
//
// A sequence is a list of Blocks. A pose block is one leaf move; a repeat
// block wraps a nested list of blocks (which may itself contain repeat
// blocks), mirroring a Scratch-style "repeat" C-block — multiple loops can
// exist side by side, and loops can nest inside loops.
//
// Reordering and nesting both go through moveBlock(), which locates
// positions by block uid rather than numeric index, so it never has to
// reason about index shifts caused by removing a block from one spot before
// inserting it in another.

import type { DancePoseId, DanceSpeed } from './poses'

export interface PoseBlockT {
  type: 'pose'
  uid: string
  poseId: DancePoseId
  speed: DanceSpeed
}

export interface RepeatBlockT {
  type: 'repeat'
  uid: string
  count: number
  children: Block[]
}

export type Block = PoseBlockT | RepeatBlockT

export function newPoseBlock(poseId: DancePoseId): PoseBlockT {
  return { type: 'pose', uid: crypto.randomUUID(), poseId, speed: 'normal' }
}

export function newRepeatBlock(): RepeatBlockT {
  return { type: 'repeat', uid: crypto.randomUUID(), count: 2, children: [] }
}

/** Apply `fn` to the block with `uid`, wherever it is in the tree. */
export function mapBlock(blocks: Block[], uid: string, fn: (b: Block) => Block): Block[] {
  return blocks.map((b) => {
    if (b.uid === uid) return fn(b)
    if (b.type === 'repeat') return { ...b, children: mapBlock(b.children, uid, fn) }
    return b
  })
}

/** Remove the block with `uid` from wherever it is in the tree. */
export function removeBlock(blocks: Block[], uid: string): { tree: Block[]; removed: Block | null } {
  let removed: Block | null = null
  const tree = blocks.reduce<Block[]>((acc, b) => {
    if (b.uid === uid) {
      removed = b
      return acc
    }
    if (b.type === 'repeat') {
      const inner = removeBlock(b.children, uid)
      if (inner.removed) removed = inner.removed
      acc.push({ ...b, children: inner.tree })
      return acc
    }
    acc.push(b)
    return acc
  }, [])
  return { tree, removed }
}

/** True if `uid` is `node` itself or anywhere inside its subtree. */
function containsUid(node: Block, uid: string): boolean {
  if (node.uid === uid) return true
  if (node.type === 'repeat') return node.children.some((c) => containsUid(c, uid))
  return false
}

/**
 * Insert `block` into `parentUid`'s children (or the top level, if null),
 * just before `beforeUid` (or at the end, if null or not found there).
 */
function insertBefore(
  blocks: Block[],
  parentUid: string | null,
  beforeUid: string | null,
  block: Block,
): Block[] {
  if (parentUid === null) {
    const idx = beforeUid ? blocks.findIndex((b) => b.uid === beforeUid) : -1
    const at = idx === -1 ? blocks.length : idx
    return [...blocks.slice(0, at), block, ...blocks.slice(at)]
  }
  return blocks.map((b) => {
    if (b.uid === parentUid && b.type === 'repeat') {
      const idx = beforeUid ? b.children.findIndex((c) => c.uid === beforeUid) : -1
      const at = idx === -1 ? b.children.length : idx
      return { ...b, children: [...b.children.slice(0, at), block, ...b.children.slice(at)] }
    }
    if (b.type === 'repeat') return { ...b, children: insertBefore(b.children, parentUid, beforeUid, block) }
    return b
  })
}

/**
 * Move the block with `sourceUid` so it sits just before `beforeUid` inside
 * `destParentUid`'s children (top level if null). No-ops if the move would
 * drop a block into itself or into its own subtree (which would otherwise
 * create a cycle), or if the source can't be found.
 */
export function moveBlock(
  blocks: Block[],
  sourceUid: string,
  destParentUid: string | null,
  beforeUid: string | null,
): Block[] {
  if (sourceUid === destParentUid || sourceUid === beforeUid) return blocks
  const { tree, removed } = removeBlock(blocks, sourceUid)
  if (!removed) return blocks
  if (destParentUid !== null && containsUid(removed, destParentUid)) return blocks
  return insertBefore(tree, destParentUid, beforeUid, removed)
}
