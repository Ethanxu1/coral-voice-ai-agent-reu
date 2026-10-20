import { useState } from 'react'
import { Link } from 'react-router-dom'
import { movePulses, setPose, type SetPoseResult } from '../api/robot'
import RobotViewer from '../components/RobotViewer'
import { PI_BASE } from '../config'
import { JOINT_GROUPS, STAND_PULSES, jointLabel } from '../robot/joints'
import './PoseTester.css'

type Target = 'sim' | 'robot' | 'both'

const TARGET_LABEL: Record<Target, string> = {
  sim: 'Sim',
  robot: 'Robot',
  both: 'Sim + Robot',
}

const MIN_PULSE = 0
const MAX_PULSE = 1000

type Tone = 'ok' | 'warn' | 'error'
interface StatusLine {
  tone: Tone
  text: string
}

/** Kept as text so a half-typed value doesn't jump around while editing. */
type PulseInputs = Record<string, string>

function standInputs(): PulseInputs {
  return Object.fromEntries(Object.entries(STAND_PULSES).map(([j, p]) => [j, String(p)]))
}

function parsePulse(raw: string): number | null {
  if (!/^\d+$/.test(raw.trim())) return null
  const value = Number(raw)
  return value >= MIN_PULSE && value <= MAX_PULSE ? value : null
}

function describeSim(result: SetPoseResult): StatusLine {
  const { safety } = result
  if (result.status === 'blocked') {
    return { tone: 'error', text: "Sim: blocked — this pose would make the robot fall over, so nothing moved." }
  }
  if (safety.collisionClamped) {
    return {
      tone: 'warn',
      text: `Sim: stopped at ${Math.round(safety.safeFraction * 100)}% of the way to avoid a collision` +
        (safety.badPairs.length ? ` (${safety.badPairs.join(', ')})` : '') + '.',
    }
  }
  return { tone: 'ok', text: `Sim: moved ${result.applied.length} joint(s).` }
}

/** Set every servo's hardware pulse and send the pose to the sim, the physical
 *  robot, or both. Sim goes through the backend's /set-pose (collision + fall
 *  checked, glides over the move time); robot goes straight to the Pi's /move. */
export default function PoseTester() {
  const [inputs, setInputs] = useState<PulseInputs>(standInputs)
  const [target, setTarget] = useState<Target>('sim')
  const [durationMs, setDurationMs] = useState(1000)
  const [collisionCheck, setCollisionCheck] = useState(true)
  const [status, setStatus] = useState<StatusLine[]>([])
  const [busy, setBusy] = useState(false)

  const invalid = Object.keys(inputs).filter((j) => parsePulse(inputs[j]) === null)

  const apply = async () => {
    if (invalid.length > 0) return
    const pulses = Object.fromEntries(Object.entries(inputs).map(([j, raw]) => [j, Number(raw)]))
    setBusy(true)
    setStatus([])

    // Run the selected targets in parallel and report each independently, so
    // an unreachable Pi doesn't hide a successful sim move (and vice versa).
    const lines: StatusLine[] = []
    const jobs: Promise<void>[] = []
    const failed = (who: string) => (e: unknown) => {
      lines.push({ tone: 'error', text: `${who}: ${e instanceof Error ? e.message : String(e)}` })
    }
    if (target !== 'robot') {
      jobs.push(
        setPose(pulses, { durationMs, skipCollisionCheck: !collisionCheck })
          .then((r) => { lines.push(describeSim(r)) })
          .catch(failed('Sim')),
      )
    }
    if (target !== 'sim') {
      jobs.push(
        movePulses(pulses, durationMs)
          .then(({ count }) => { lines.push({ tone: 'ok', text: `Robot: moved ${count} servo(s).` }) })
          .catch(failed('Robot')),
      )
    }
    await Promise.all(jobs)
    setStatus(lines)
    setBusy(false)
  }

  return (
    <div className="pt-page">
      <div>
        <header className="pt-header">
          <Link to="/"><button className="primitives-test-btn">← Back</button></Link>
          <h2>Pose Tester</h2>
        </header>
        <p className="pt-intro">
          Set each servo's hardware pulse ({MIN_PULSE}–{MAX_PULSE}, the units used in{' '}
          <code>motions.py</code>). Values start at the stand pose; changed joints are highlighted.
        </p>

        <div className="pt-controls">
          <span className="pt-controls-label">Send to:</span>
          {(['sim', 'robot', 'both'] as Target[]).map((t) => (
            <label key={t}>
              <input type="radio" name="pose-target" checked={target === t} onChange={() => setTarget(t)} disabled={busy} />
              {TARGET_LABEL[t]}
            </label>
          ))}
          {target !== 'robot' && (
            <label>
              <input type="checkbox" checked={collisionCheck} onChange={(e) => setCollisionCheck(e.target.checked)} disabled={busy} />
              Safety check (sim)
            </label>
          )}
          <label className="pt-move-time">
            Move time (ms):
            <input
              type="number"
              min={100}
              step={100}
              value={durationMs}
              onChange={(e) => setDurationMs(Math.max(100, parseInt(e.target.value, 10) || 100))}
              disabled={busy}
            />
          </label>
        </div>

        {target !== 'sim' && (
          <div className="pt-warning">
            Robot target sends pulses straight to the <strong>physical robot</strong> at{' '}
            <code>{PI_BASE}</code>, without the safety check. Make sure it's standing clear.
          </div>
        )}

        <div className="pt-groups">
          {JOINT_GROUPS.map((group) => (
            <fieldset key={group.title} className="pt-group">
              <legend>{group.title}</legend>
              {group.joints.map((joint) => {
                const value = inputs[joint]
                const bad = parsePulse(value) === null
                const changed = !bad && Number(value) !== STAND_PULSES[joint]
                return (
                  <label key={joint} className="pt-joint" title={joint}>
                    <span>{jointLabel(joint)}</span>
                    <input
                      type="number"
                      inputMode="numeric"
                      min={MIN_PULSE}
                      max={MAX_PULSE}
                      step={5}
                      value={value}
                      onChange={(e) => setInputs((prev) => ({ ...prev, [joint]: e.target.value }))}
                      className={bad ? 'pt-invalid' : changed ? 'pt-changed' : undefined}
                      aria-invalid={bad}
                      disabled={busy}
                    />
                  </label>
                )
              })}
            </fieldset>
          ))}
        </div>

        <div className="pt-actions">
          <button className="primitives-test-btn" onClick={apply} disabled={busy || invalid.length > 0}>
            {busy ? 'Applying…' : `▶ Apply to ${TARGET_LABEL[target]}`}
          </button>
          <button className="primitives-test-btn" onClick={() => setInputs(standInputs())} disabled={busy}>
            Reset values to stand
          </button>
          {invalid.length > 0 && (
            <span className="pt-error-text">
              Enter a whole number from {MIN_PULSE} to {MAX_PULSE} for: {invalid.map(jointLabelWithSide).join(', ')}
            </span>
          )}
        </div>

        {status.map((line, i) => (
          <div key={i} className={`pt-status pt-status-${line.tone}`} role="status">{line.text}</div>
        ))}
      </div>

      <section className="pt-sim" aria-label="Simulator">
        <div className="pt-sim-title">Simulator</div>
        <div className="pt-sim-view">
          <RobotViewer embedded />
        </div>
        <div className="pt-sim-note">
          Live view of the MuJoCo sim. It changes when you apply to Sim or Sim + Robot.
        </div>
      </section>
    </div>
  )
}

function jointLabelWithSide(joint: string): string {
  const side = joint.startsWith('l_') ? 'left ' : joint.startsWith('r_') ? 'right ' : 'head '
  return side + jointLabel(joint).toLowerCase()
}
