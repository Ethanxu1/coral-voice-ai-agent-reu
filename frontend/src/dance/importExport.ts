// Import/export for dance moves (individual poses) and programs (Blockly
// workspace + referenced moves). Programs bundle the move data they need so a
// recipient can import the missing ones.

import { loadCustomPoses, importCustomPoses } from '../poseDesigner/customPoses'

// ── File format types ───────────────────────────────────────────────────

interface MovesFile {
  type: 'coral-moves'
  version: 1
  moves: { name: string; pulses: Record<string, number> }[]
}

interface ProgramFile {
  type: 'coral-program'
  version: 1
  workspace: object
  moves: Record<string, { name: string; pulses: Record<string, number> }>
}

// ── Helpers ─────────────────────────────────────────────────────────────

function download(data: object, filename: string) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function pickFile(): Promise<string> {
  return new Promise((resolve, reject) => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.json'
    input.onchange = () => {
      const file = input.files?.[0]
      if (!file) return reject(new Error('No file selected'))
      file.text().then(resolve, reject)
    }
    input.click()
  })
}

function parseJson(text: string): unknown {
  try { return JSON.parse(text) } catch { return null }
}

function isMovesFile(data: unknown): data is MovesFile {
  if (!data || typeof data !== 'object') return false
  const d = data as Record<string, unknown>
  return d.type === 'coral-moves' && d.version === 1 && Array.isArray(d.moves)
}

function isProgramFile(data: unknown): data is ProgramFile {
  if (!data || typeof data !== 'object') return false
  const d = data as Record<string, unknown>
  return d.type === 'coral-program' && d.version === 1 && !!d.workspace && typeof d.workspace === 'object' && !!d.moves && typeof d.moves === 'object'
}

/** Walk a serialized Blockly workspace, calling `visit` on every block. */
function walkBlocks(state: any, visit: (block: any) => void) {
  function walk(block: any) {
    if (!block) return
    visit(block)
    if (block.next?.block) walk(block.next.block)
    if (block.inputs) {
      for (const inp of Object.values(block.inputs) as any[]) {
        if (inp?.block) walk(inp.block)
      }
    }
  }
  const top = state?.blocks?.blocks
  if (Array.isArray(top)) top.forEach(walk)
}

// ── Export ───────────────────────────────────────────────────────────────

export function exportMoves() {
  const moves = loadCustomPoses()
  if (moves.length === 0) throw new Error('No moves to export')
  const file: MovesFile = {
    type: 'coral-moves',
    version: 1,
    moves: moves.map((p) => ({ name: p.name, pulses: p.pulses })),
  }
  download(file, 'coral-moves.json')
}

export function exportProgram(workspaceState: object) {
  const poseIds = new Set<string>()
  walkBlocks(workspaceState, (b) => {
    if (b.type === 'dance_custom' && b.fields?.POSE) poseIds.add(b.fields.POSE)
  })
  const allPoses = loadCustomPoses()
  const moves: ProgramFile['moves'] = {}
  for (const id of poseIds) {
    const p = allPoses.find((x) => x.id === id)
    if (p) moves[id] = { name: p.name, pulses: p.pulses }
  }
  const file: ProgramFile = {
    type: 'coral-program',
    version: 1,
    workspace: workspaceState,
    moves,
  }
  download(file, 'coral-program.json')
}

// ── Import ──────────────────────────────────────────────────────────────

export interface ImportMovesResult { imported: number; skipped: number }

export async function importMovesFromFile(): Promise<ImportMovesResult | null> {
  let text: string
  try { text = await pickFile() } catch { return null }
  const data = parseJson(text)
  if (!isMovesFile(data)) throw new Error('Not a valid CORAL moves file')
  const total = data.moves.length
  const imported = importCustomPoses(data.moves)
  return { imported, skipped: total - imported }
}

export interface MissingMove {
  originalId: string
  name: string
  pulses: Record<string, number>
}

export interface ProgramImportData {
  workspace: object
  moves: ProgramFile['moves']
  missing: MissingMove[]
}

export async function parseProgramFile(): Promise<ProgramImportData | null> {
  let text: string
  try { text = await pickFile() } catch { return null }
  const data = parseJson(text)
  if (!isProgramFile(data)) throw new Error('Not a valid CORAL program file')

  const existingNames = new Set(loadCustomPoses().map((p) => p.name.toLowerCase()))
  const missing: MissingMove[] = []
  for (const [id, move] of Object.entries(data.moves)) {
    if (!existingNames.has(move.name.toLowerCase())) {
      missing.push({ originalId: id, name: move.name, pulses: move.pulses })
    }
  }
  return { workspace: data.workspace, moves: data.moves, missing }
}

/** Import the missing moves and remap old IDs to local IDs in the workspace state. */
export function finalizeProgramImport(data: ProgramImportData): object {
  if (data.missing.length > 0) {
    importCustomPoses(data.missing.map((m) => ({ name: m.name, pulses: m.pulses })))
  }

  const local = loadCustomPoses()
  const nameToLocalId = new Map(local.map((p) => [p.name.toLowerCase(), p.id]))
  const clone = JSON.parse(JSON.stringify(data.workspace))

  walkBlocks(clone, (block) => {
    if (block.type === 'dance_custom' && block.fields?.POSE) {
      const oldId = block.fields.POSE
      const move = data.moves[oldId]
      if (move) {
        const localId = nameToLocalId.get(move.name.toLowerCase())
        if (localId) block.fields.POSE = localId
      }
    }
  })
  return clone
}
