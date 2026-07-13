import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { setPose } from '../demo/api'
import { useRobotConfig } from '../demo/robotConfig'

/** The 24 servo joints the sim knows about (matches server SERVO_ID_MAP). */
const KNOWN_JOINTS = new Set([
  'l_ank_roll', 'r_ank_roll', 'l_ank_pitch', 'r_ank_pitch',
  'l_knee', 'r_knee', 'l_hip_pitch', 'r_hip_pitch',
  'l_hip_roll', 'r_hip_roll', 'l_hip_yaw', 'r_hip_yaw',
  'l_sho_pitch', 'r_sho_pitch', 'l_sho_roll', 'r_sho_roll',
  'l_el_pitch', 'r_el_pitch', 'l_el_yaw', 'r_el_yaw',
  'l_gripper', 'r_gripper', 'head_pan', 'head_tilt',
])

// A neutral starting point in the exact motions.py format.
const STAND_EXAMPLE = `'l_ank_roll':  500,  'r_ank_roll':  500,
'l_ank_pitch': 640,  'r_ank_pitch': 360,
'l_knee':      500,  'r_knee':      500,
'l_hip_pitch': 350,  'r_hip_pitch': 650,
'l_hip_roll':  500,  'r_hip_roll':  500,
'l_hip_yaw':   500,  'r_hip_yaw':   500,
'l_sho_pitch': 835,  'r_sho_pitch': 165,
'l_sho_roll':  830,  'r_sho_roll':  170,
'l_el_pitch':  500,  'r_el_pitch':  500,
'l_el_yaw':    150,  'r_el_yaw':    850,
'l_gripper':   500,  'r_gripper':   500,
'head_pan':    500,  'head_tilt':   500,`

// Extract every `name: number` pair from pasted text, tolerating quotes, commas,
// and braces so the raw motions.py dict body pastes in as-is.
const PAIR_RE = /(['"]?)([a-z_][a-z0-9_]*)\1\s*:\s*(-?\d+)/gi

interface Parsed {
  pulses: Record<string, number>
  unknown: string[]
}

function parsePulses(text: string): Parsed {
  const pulses: Record<string, number> = {}
  const unknown: string[] = []
  for (const m of text.matchAll(PAIR_RE)) {
    const name = m[2]
    const value = parseInt(m[3], 10)
    if (KNOWN_JOINTS.has(name)) pulses[name] = value
    else unknown.push(name)
  }
  return { pulses, unknown }
}

/** Paste a raw pulse dict (motions.py format) and push it to the sim. */
export default function PoseTester() {
  const { mode } = useRobotConfig()
  const [text, setText] = useState(STAND_EXAMPLE)
  const [status, setStatus] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const { pulses, unknown } = useMemo(() => parsePulses(text), [text])
  const names = Object.keys(pulses)

  const apply = async () => {
    if (names.length === 0) {
      setStatus('Nothing to apply — no joint: pulse pairs found.')
      return
    }
    setBusy(true)
    setStatus(null)
    try {
      const { applied, skipped } = await setPose(pulses)
      setStatus(
        `Applied ${applied.length} joint(s)` +
          (skipped.length ? ` — skipped ${skipped.length}: ${skipped.join(', ')}` : ''),
      )
    } catch (e) {
      setStatus(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ maxWidth: 760, margin: '0 auto', padding: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
        <Link to="/"><button className="primitives-test-btn">← Back</button></Link>
        <h2 style={{ margin: 0 }}>Pose Tester</h2>
      </div>

      <p style={{ opacity: 0.7, fontSize: 14, marginTop: 0 }}>
        Paste a pulse dict in <code>motions.py</code> format
        (<code>'joint': pulse,</code>). Values are hardware pulses (0–1000); the sim
        converts and clamps them. Applies to the <strong>simulation</strong> only.
      </p>

      {mode === 'hardware' && (
        <div style={{ background: '#fff3cd', color: '#664d03', padding: '8px 12px', borderRadius: 6, fontSize: 13, marginBottom: 12 }}>
          Robot mode is set to <strong>Physical Robot</strong>, but Pose Tester always drives the sim server.
        </div>
      )}

      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        spellCheck={false}
        style={{
          width: '100%', minHeight: 260, fontFamily: 'monospace', fontSize: 13,
          padding: 12, borderRadius: 8, border: '1px solid #ccc', resize: 'vertical',
        }}
      />

      <div style={{ display: 'flex', alignItems: 'center', gap: 12, margin: '12px 0' }}>
        <button className="primitives-test-btn" onClick={apply} disabled={busy || names.length === 0}>
          {busy ? 'Applying…' : `▶ Apply to Sim (${names.length})`}
        </button>
        <button className="primitives-test-btn" onClick={() => setText(STAND_EXAMPLE)} disabled={busy}>
          Reset to Stand
        </button>
        {unknown.length > 0 && (
          <span style={{ color: '#b02a37', fontSize: 13 }}>
            Unknown joint(s) ignored: {[...new Set(unknown)].join(', ')}
          </span>
        )}
      </div>

      {status && (
        <div style={{ fontSize: 13, padding: '8px 12px', borderRadius: 6, background: '#e7f1ff', color: '#084298' }}>
          {status}
        </div>
      )}

      {names.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Parsed {names.length} joint(s):</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 4 }}>
            {names.map((n) => (
              <div key={n} style={{ fontFamily: 'monospace', fontSize: 12, background: '#f6f8fa', padding: '2px 6px', borderRadius: 4 }}>
                {n}: {pulses[n]}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
