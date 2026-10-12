import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import RobotViewer from '../components/RobotViewer'
import { getJointPulses, stopSubjectSelection } from '../demo/api'
import GestureFigure from '../rps/GestureFigure'
import { poseRobot, resetRobot } from '../rps/robotPose'
import { figureFromPose } from '../rps/gestures'
import GestureTopbar, { GESTURES_PATH } from '../gestures/GestureTopbar'
import {
  ARM_JOINT_DEFS,
  ARM_JOINT_IDS,
  PULSE_MAX,
  PULSE_MIN,
  armPulses,
  jointId,
  mirrorJoint,
  mirrorPulse,
  pulseToDegreesLabel,
  type ArmSide,
} from '../gestures/armJoints'
import {
  deleteGesture,
  downloadJson,
  importJson,
  updateGesture,
  useGestures,
  type Gesture,
} from '../gestures/library'
import './RefinedDemo.css'
import './RockPaperScissors.css'
import './GestureStudio.css'

/** Pulses one click of the − / + buttons moves a joint (about 1 degree). */
const NUDGE = 5
/** Easing time when switching to another gesture, and while dragging a slider. */
const SWITCH_MS = 700
const TUNE_MS = 150
/** Wait this long after the last slider change before moving the robot. */
const DEBOUNCE_MS = 80
/** Let the physics settle before reading back where the arms actually went. */
const SETTLE_MS = 400
/** A joint further than this from its target didn't get there (joint limit or self-collision). */
const REACH_TOLERANCE = 40

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))

const samePulses = (a: Record<string, number>, b: Record<string, number>) =>
  ARM_JOINT_IDS.every((j) => a[j] === b[j])

const SIDE_LABEL: Record<ArmSide, string> = { l: "CORAL's left arm", r: "CORAL's right arm" }

function formatDate(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

/**
 * Gesture Studio, library: every saved gesture in a list on the left. Picking
 * one shows it on the simulator robot and as a stick figure, and lets CORAL's
 * version be fine-tuned joint by joint. Gestures can be imported from and
 * exported to JSON files.
 */
export default function GestureLibrary() {
  const gestures = useGestures()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const selected = gestures.find((g) => g.id === selectedId) ?? null
  // CORAL's pose being tuned, not yet saved.
  const [draft, setDraft] = useState<Record<string, number> | null>(null)
  const [mirror, setMirror] = useState(false)
  const [notice, setNotice] = useState<{ text: string; warn: boolean } | null>(null)
  const [unreached, setUnreached] = useState<string[]>([])
  const [robotReady, setRobotReady] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  // Whether the next robot move is a switch to another gesture (slow) or a tweak (fast).
  const switchingRef = useRef(true)

  const dirty = !!selected && !!draft && !samePulses(draft, selected.robotPulses)

  // Start from a clean stand so poseRobot eases from a known pose.
  useEffect(() => {
    stopSubjectSelection()
    resetRobot()
      .catch(() => {})
      .finally(() => setRobotReady(true))
    return () => {
      resetRobot().catch(() => {})
    }
  }, [])

  // Select the first gesture when nothing (or a deleted one) is selected.
  useEffect(() => {
    if (!selected && gestures.length > 0) select(gestures[0], true)
    if (gestures.length === 0) {
      setSelectedId(null)
      setDraft(null)
    }
  }, [gestures, selected])

  // Move the robot to the draft, then check it actually got there.
  useEffect(() => {
    if (!draft || !robotReady) return
    let cancelled = false
    const duration = switchingRef.current ? SWITCH_MS : TUNE_MS
    switchingRef.current = false
    const timer = setTimeout(async () => {
      try {
        await poseRobot(draft, duration)
        await sleep(SETTLE_MS)
        if (cancelled) return
        const actual = armPulses(await getJointPulses())
        if (cancelled) return
        setUnreached(ARM_JOINT_IDS.filter((j) => j in actual && Math.abs(actual[j] - draft[j]) > REACH_TOLERANCE))
      } catch (e) {
        if (!cancelled) console.warn('posing robot failed', e)
      }
    }, DEBOUNCE_MS)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [draft, robotReady])

  function select(g: Gesture, force = false) {
    if (!force && g.id === selectedId) return
    if (!force && dirty && !window.confirm(`Discard your unsaved changes to "${selected!.name}"?`)) return
    switchingRef.current = true
    setSelectedId(g.id)
    setDraft({ ...g.robotPulses })
    setUnreached([])
  }

  function setJoint(joint: string, value: number) {
    const v = Math.round(Math.min(PULSE_MAX, Math.max(PULSE_MIN, value)))
    setDraft((d) => {
      if (!d) return d
      const next = { ...d, [joint]: v }
      if (mirror) next[mirrorJoint(joint)] = mirrorPulse(v)
      return next
    })
  }

  function saveDraft() {
    if (!selected || !draft) return
    updateGesture(selected.id, { robotPulses: draft })
    setNotice({ text: `Saved CORAL's pose for "${selected.name}".`, warn: false })
  }

  function resetToRecorded() {
    if (!selected) return
    setDraft({ ...selected.recordedPulses })
  }

  function remove() {
    if (!selected) return
    if (!window.confirm(`Delete "${selected.name}"? This can't be undone (export it first if you might want it back).`)) return
    const at = gestures.findIndex((g) => g.id === selected.id)
    const next = gestures[at + 1] ?? gestures[at - 1]
    deleteGesture(selected.id)
    if (next) select(next, true)
  }

  async function onImportFile(file: File) {
    try {
      const r = importJson(await file.text())
      const parts = [`${r.added} added`]
      if (r.updated) parts.push(`${r.updated} updated`)
      if (r.skipped) parts.push(`${r.skipped} already up to date`)
      if (r.invalid) parts.push(`${r.invalid} unreadable`)
      setNotice({ text: `Imported ${file.name}: ${parts.join(', ')}.`, warn: r.invalid > 0 })
    } catch (e) {
      setNotice({ text: e instanceof Error ? e.message : 'Import failed.', warn: true })
    }
  }

  return (
    <div className="rd-root">
      <GestureTopbar title="Gesture library" />

      <main className="gs-library">
        {/* The list of gestures, plus import and export. */}
        <aside className="gs-sidebar">
          <div className="gs-sidebar-head">
            <div className="gs-subhead">Gestures ({gestures.length})</div>
            <div className="gs-row">
              <button className="rps-small-btn" onClick={() => fileRef.current?.click()}>
                Import JSON
              </button>
              <button className="rps-small-btn gs-ghost" disabled={gestures.length === 0} onClick={() => downloadJson()}>
                Export all
              </button>
              <input
                ref={fileRef}
                type="file"
                accept=".json,application/json"
                hidden
                onChange={(e) => {
                  const file = e.target.files?.[0]
                  e.target.value = ''
                  if (file) onImportFile(file)
                }}
              />
            </div>
          </div>
          {notice && (
            <div className={`gs-notice ${notice.warn ? 'warn' : ''}`} onClick={() => setNotice(null)}>
              {notice.text}
            </div>
          )}
          <ul className="gs-list">
            {gestures.map((g) => (
              <li key={g.id}>
                <button className={`gs-list-item ${g.id === selectedId ? 'active' : ''}`} onClick={() => select(g)}>
                  <GestureFigure gesture={{ label: g.name, figure: figureFromPose(g.pose) }} />
                  <span className="gs-list-text">
                    <span className="gs-list-name">{g.name}</span>
                    <span className="gs-list-meta">
                      {formatDate(g.createdAt)}
                      {!samePulses(g.robotPulses, g.recordedPulses) && <span className="gs-badge">tuned</span>}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {gestures.length === 0 && (
            <div className="gs-empty">
              No gestures yet. <Link to={`${GESTURES_PATH}/record`}>Record some</Link> or import a JSON file.
            </div>
          )}
        </aside>

        {selected && draft ? (
          <section className="gs-detail">
            <div className="gs-detail-head">
              <input
                key={selected.id + selected.name}
                className="gs-input gs-title-input"
                defaultValue={selected.name}
                maxLength={60}
                aria-label="Gesture name"
                onBlur={(e) => {
                  if (e.target.value.trim() !== selected.name) updateGesture(selected.id, { name: e.target.value })
                }}
                onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
              />
              <div className="gs-row">
                <button
                  className="rps-small-btn gs-ghost"
                  onClick={() => downloadJson([selected], `${selected.name.replace(/[^\w-]+/g, '-').toLowerCase()}.json`)}
                >
                  Export this one
                </button>
                <button className="rps-small-btn gs-danger" onClick={remove}>
                  Delete
                </button>
              </div>
            </div>

            <div className="gs-views">
              <div className="rps-cell gs-view">
                <div className="rd-sim-grid" />
                <div className="rd-sim-vignette" />
                <div className="rps-cell-title">1 · Robot simulation</div>
                <RobotViewer embedded />
              </div>
              <div className="rps-cell rps-cell-dark gs-view gs-figure-view">
                <div className="rps-cell-title">2 · Stick figure (as recorded)</div>
                <GestureFigure gesture={{ label: selected.name, figure: figureFromPose(selected.pose) }} />
              </div>
            </div>

            <div className="gs-tune">
              <div className="gs-tune-head">
                <div>
                  <div className="gs-subhead">Fine-tune CORAL's pose</div>
                  <div className="gs-muted">Changes only how CORAL performs this gesture. The stick figure stays as recorded.</div>
                </div>
                <label className="gs-toggle">
                  <input type="checkbox" checked={mirror} onChange={(e) => setMirror(e.target.checked)} />
                  Mirror to the other arm
                </label>
              </div>

              <div className="gs-tune-arms">
                {(['r', 'l'] as const).map((side) => (
                  <div key={side} className="gs-tune-arm">
                    <div className="gs-tune-arm-title">{SIDE_LABEL[side]}</div>
                    {ARM_JOINT_DEFS.map((def) => {
                      const joint = jointId(side, def.key)
                      const value = draft[joint]
                      const changed = value !== selected.recordedPulses[joint]
                      return (
                        <div key={joint} className={`gs-slider ${unreached.includes(joint) ? 'unreached' : ''}`}>
                          <span className="gs-slider-label" title={`${def.hint} (${joint})`}>
                            {def.label}
                            {changed && <span className="gs-dot" title="Changed from the recording" />}
                          </span>
                          <button className="gs-nudge" aria-label={`${def.label} down`} onClick={() => setJoint(joint, value - NUDGE)}>
                            −
                          </button>
                          <input
                            type="range"
                            min={PULSE_MIN}
                            max={PULSE_MAX}
                            value={value}
                            aria-label={`${SIDE_LABEL[side]} ${def.label}`}
                            onChange={(e) => setJoint(joint, Number(e.target.value))}
                          />
                          <button className="gs-nudge" aria-label={`${def.label} up`} onClick={() => setJoint(joint, value + NUDGE)}>
                            +
                          </button>
                          <span className="gs-slider-value" title={`Servo pulse ${value}`}>
                            {pulseToDegreesLabel(value)}
                          </span>
                        </div>
                      )
                    })}
                  </div>
                ))}
              </div>

              {unreached.length > 0 && (
                <div className="gs-notice warn">
                  CORAL couldn't fully reach this pose (a joint limit, or the arm would hit the body). The highlighted
                  joints stopped short.
                </div>
              )}

              <div className="gs-row gs-tune-actions">
                <button className="rps-small-btn gs-primary" disabled={!dirty} onClick={saveDraft}>
                  Save changes
                </button>
                <button className="rps-small-btn gs-ghost" disabled={!dirty} onClick={() => setDraft({ ...selected.robotPulses })}>
                  Discard
                </button>
                <button
                  className="rps-small-btn gs-ghost"
                  disabled={samePulses(draft, selected.recordedPulses)}
                  onClick={resetToRecorded}
                >
                  Reset to recorded
                </button>
              </div>
            </div>
          </section>
        ) : (
          <section className="gs-detail gs-detail-empty">
            <div className="gs-muted">Pick a gesture on the left to see it here.</div>
          </section>
        )}
      </main>
    </div>
  )
}
