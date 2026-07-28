// Joint-angle accuracy experiment mode.
//
// Flow per trial: 3-2-1 countdown -> capture -> record the results -> wait for
// the six protractor readings -> save and advance, 9 trials in randomized
// order. The countdown, shutter, flash, DEMO_LOCKED gate and safety-verdict
// reporting are lifted from the RefinedDemo capture flow
// (frontend/src/demo/useRefinedDemoMachine.ts) so the capture the demonstrator
// experiences is the same one the demo produces.
//
// The capture request itself is server-side (POST /experiment/capture) because
// the angle math and the session files live in Python; the server runs the same
// /map-features -> /move path api.ts would have called from here.

import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { LiveStream } from './DummyStream'
import { playShutter, setRobotState, sleep } from '../demo/api'
import { useRobotConfig } from '../demo/robotConfig'
import RobotModeToggle from '../components/RobotModeToggle'
import {
  captureTrial,
  createSession,
  getSession,
  listSessions,
  recordTrial,
  type CaptureResult,
  type SessionState,
  type SessionSummary,
  type Trial,
} from '../demo/experimentApi'
import './JointAngleExperiment.css'

const ARM_LABELS: Record<string, string> = {
  robot_left: 'Robot LEFT arm (mirrors your RIGHT)',
  robot_right: 'Robot RIGHT arm (mirrors your LEFT)',
}

type ReadingDraft = Record<string, Record<string, string>>
type Status = { text: string; tone: 'ok' | 'warn' | 'bad' }

function emptyDraft(arms: string[], keys: string[]): ReadingDraft {
  return Object.fromEntries(arms.map((a) => [a, Object.fromEntries(keys.map((k) => [k, '']))]))
}

function fmt(v: number | undefined): string {
  return v === undefined ? 'gated' : v.toFixed(1)
}

export default function JointAngleExperiment() {
  const { simOnly, legMode } = useRobotConfig()
  const [session, setSession] = useState<SessionState | null>(null)
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [index, setIndex] = useState(0)
  const [countdown, setCountdown] = useState<number | null>(null)
  const [flash, setFlash] = useState(false)
  const [busy, setBusy] = useState(false)
  const [capture, setCapture] = useState<CaptureResult | null>(null)
  const [draft, setDraft] = useState<ReadingDraft>({})
  const [notes, setNotes] = useState('')
  const [status, setStatus] = useState<Status | null>(null)
  const [dispatchMoves, setDispatchMoves] = useState(true)

  const [form, setForm] = useState({
    seed: 0,
    demonstrator: '',
    camera_height_cm: '',
    camera_distance_cm: '',
    lighting: '',
  })

  const measurements = session?.measurements ?? []
  const arms = useMemo(() => (session?.arms ?? []).map((a) => a.arm), [session])
  const trial: Trial | undefined = session?.trials[index]

  useEffect(() => {
    listSessions()
      .then((r) => setSessions(r.sessions))
      .catch(() => setSessions([]))
  }, [])

  // Reset the entry form whenever the trial changes, pre-filling from a trial
  // that was already recorded so revisiting one shows what was entered.
  useEffect(() => {
    if (!trial || measurements.length === 0) return
    const keys = measurements.map((m) => m.key)
    const next = emptyDraft(arms, keys)
    for (const arm of arms) {
      for (const k of keys) {
        const v = trial.robot?.[arm]?.[k]
        if (v !== undefined) next[arm][k] = String(v)
      }
    }
    setDraft(next)
    setNotes(trial.notes ?? '')
    setCapture(null)
    setStatus(
      trial.recorded
        ? { text: 'Reviewing a recorded trial — recapture to overwrite.', tone: 'warn' }
        : { text: 'Get into pose, then press Capture.', tone: 'ok' },
    )
  }, [trial?.order_index, measurements.length, arms.join(',')]) // eslint-disable-line react-hooks/exhaustive-deps

  const applySession = useCallback((s: SessionState, goTo?: number) => {
    setSession(s)
    const target = goTo ?? s.next_unrecorded ?? 1
    const i = s.trials.findIndex((t) => t.order_index === target)
    setIndex(i >= 0 ? i : 0)
  }, [])

  const startSession = async () => {
    setBusy(true)
    try {
      applySession(await createSession(form))
    } catch (e) {
      setStatus({ text: String(e), tone: 'bad' })
    } finally {
      setBusy(false)
    }
  }

  const resumeSession = async (id: string) => {
    setBusy(true)
    try {
      applySession(await getSession(id))
    } catch (e) {
      setStatus({ text: String(e), tone: 'bad' })
    } finally {
      setBusy(false)
    }
  }

  const onCapture = async () => {
    if (!session || !trial || busy) return
    setBusy(true)
    setCapture(null)
    try {
      // DEMO_LOCKED during the countdown, exactly as the demo does, so nothing
      // else drives the robot while the demonstrator is holding the pose.
      await setRobotState('DEMO_LOCKED')
      for (const n of [3, 2, 1]) {
        setCountdown(n)
        await sleep(1000)
      }
      setCountdown(null)
      setFlash(true)
      playShutter()
      setStatus({ text: 'Capturing…', tone: 'ok' })

      const result = await captureTrial(session.session_id, trial.order_index, dispatchMoves)
      setTimeout(() => setFlash(false), 350)
      await setRobotState('IDLE')

      if (!result.captured) {
        setStatus({ text: result.detail ?? 'Capture failed — recapture.', tone: 'bad' })
        return
      }
      setCapture(result)
      // Keep the local trial in sync so Back/Skip still shows this capture.
      setSession((s) =>
        s
          ? {
              ...s,
              trials: s.trials.map((t) =>
                t.order_index === result.trial!.order_index ? result.trial! : t,
              ),
            }
          : s,
      )

      if (!dispatchMoves) {
        setStatus({
          text: 'Captured (no dispatch). Drive the robot to this pose before measuring.',
          tone: 'warn',
        })
      } else if (result.blocked || result.safety?.fall_blocked) {
        setStatus({
          text: 'FALL CHECK BLOCKED the move — 0% executed. Recapture; do not measure this pose.',
          tone: 'bad',
        })
      } else if (result.safety?.collision_clamped) {
        setStatus({
          text: `Collision clamp: move pulled back to ${Math.round(
            (result.safety.safe_fraction ?? 0) * 100,
          )}%. Recorded — measure the pose the robot is actually holding.`,
          tone: 'warn',
        })
      } else {
        setStatus({ text: 'Safety check passed. Let it settle, then measure.', tone: 'ok' })
      }
    } catch (e) {
      setCountdown(null)
      setFlash(false)
      setStatus({ text: String(e), tone: 'bad' })
    } finally {
      setBusy(false)
    }
  }

  const onSave = async () => {
    if (!session || !trial || busy) return
    const readings: Record<string, Record<string, number>> = {}
    for (const arm of arms) {
      readings[arm] = {}
      for (const m of measurements) {
        const raw = (draft[arm]?.[m.key] ?? '').trim()
        if (raw === '') {
          setStatus({ text: `${m.label} — ${arm} is empty.`, tone: 'bad' })
          return
        }
        const val = Number(raw)
        if (!Number.isFinite(val)) {
          setStatus({ text: `${m.label} — ${arm}: "${raw}" is not a number.`, tone: 'bad' })
          return
        }
        if (val < -180 || val > 180) {
          setStatus({ text: `${m.label} — ${arm}: ${val} is outside -180..180.`, tone: 'bad' })
          return
        }
        readings[arm][m.key] = val
      }
    }

    setBusy(true)
    try {
      const updated = await recordTrial(session.session_id, trial.order_index, readings, notes)
      if (updated.next_unrecorded === null) {
        setSession(updated)
        setStatus({ text: `All ${updated.total} trials recorded — ${updated.csv_path}`, tone: 'ok' })
        return
      }
      applySession(updated)
    } catch (e) {
      setStatus({ text: String(e), tone: 'bad' })
    } finally {
      setBusy(false)
    }
  }

  // ── setup screen ──
  if (!session) {
    return (
      <div className="jx-root">
        <header className="jx-topbar">
          <Link to="/" className="jx-back">← Home</Link>
          <h1>Joint Angle Accuracy Experiment</h1>
        </header>
        <div className="jx-setup">
          <div className="jx-card">
            <h2>New session</h2>
            <p className="jx-hint">
              9 trials: 3 arm poses × 3 reps, randomized.
              Written to <code>data/experiments/joint_angle/</code>.
            </p>
            <label>Demonstrator ID
              <input value={form.demonstrator}
                onChange={(e) => setForm({ ...form, demonstrator: e.target.value })} />
            </label>
            <label>Camera height (cm)
              <input value={form.camera_height_cm}
                onChange={(e) => setForm({ ...form, camera_height_cm: e.target.value })} />
            </label>
            <label>Camera distance (cm)
              <input value={form.camera_distance_cm}
                onChange={(e) => setForm({ ...form, camera_distance_cm: e.target.value })} />
            </label>
            <label>Lighting
              <input value={form.lighting}
                onChange={(e) => setForm({ ...form, lighting: e.target.value })} />
            </label>
            <label>Trial-order seed
              <input type="number" value={form.seed}
                onChange={(e) => setForm({ ...form, seed: Number(e.target.value) })} />
            </label>
            <button className="jx-primary" disabled={busy} onClick={startSession}>
              Start session
            </button>
          </div>

          <div className="jx-card">
            <h2>Resume</h2>
            {sessions.length === 0 && <p className="jx-hint">No previous sessions.</p>}
            {sessions.map((s) => (
              <button key={s.session_id} className="jx-session-row"
                disabled={busy} onClick={() => resumeSession(s.session_id)}>
                <span className="jx-session-id">{s.session_id}</span>
                <span className="jx-session-meta">
                  {s.demonstrator || '—'} · {s.recorded_count}/{s.total} recorded
                </span>
              </button>
            ))}
          </div>
        </div>
        {status && <div className={`jx-status jx-${status.tone}`}>{status.text}</div>}
      </div>
    )
  }

  // ── trial screen ──
  const shown = capture?.trial ?? trial
  const clamped = new Set((shown?.clamped ?? []).map(([a, k]) => `${a}/${k}`))
  const hasCapture = !!shown?.captured

  return (
    <div className="jx-root">
      <header className="jx-topbar">
        <Link to="/" className="jx-back">← Home</Link>
        <h1>Joint Angle Accuracy</h1>
        <span className="jx-session-tag">{session.session_id}</span>
        <RobotModeToggle />
        <label className="jx-toggle">
          <input type="checkbox" checked={dispatchMoves}
            onChange={(e) => setDispatchMoves(e.target.checked)} />
          Dispatch to robot
        </label>
        <span className="jx-progress">{session.recorded_count} / {session.total} recorded</span>
      </header>

      <main className="jx-main">
        <section className="jx-camera">
          <LiveStream badge={false} className="jx-stream" />
          <div className="jx-live-badge"><span className="jx-live-dot" />LIVE</div>
          {flash && <div className="jx-flash" />}
          {countdown !== null && (
            <div className="jx-countdown">
              <div className="jx-countdown-card">
                <div className="jx-countdown-label">Get ready!</div>
                <span key={countdown} className="jx-countdown-num">{countdown}</span>
              </div>
            </div>
          )}
          {capture?.image_b64 && (
            <img className="jx-captured" alt="Captured frame"
              src={`data:image/jpeg;base64,${capture.image_b64}`} />
          )}
        </section>

        <section className="jx-panel">
          {trial && (
            <div className="jx-trial-head">
              <div className="jx-trial-title">
                Trial {index + 1} of {session.total} · {trial.pose_label} · rep {trial.rep}
              </div>
              <div className="jx-cue">
                {trial.cue}. Match the pose on both arms and hold still.
              </div>
              <div className="jx-nominal">
                Nominal: {measurements.map((m) => `${m.label} ${trial.nominal[m.key]}°`).join(' · ')}
              </div>
            </div>
          )}

          <div className="jx-actions">
            <button className="jx-primary" disabled={busy} onClick={onCapture}>
              {busy ? 'Working…' : 'Capture pose'}
            </button>
            <button disabled={busy || index === 0} onClick={() => setIndex(index - 1)}>Back</button>
            <button disabled={busy || index >= session.trials.length - 1}
              onClick={() => setIndex(index + 1)}>Skip</button>
            <button className="jx-primary" disabled={busy || !hasCapture} onClick={onSave}>
              Save &amp; next
            </button>
          </div>

          <table className="jx-table">
            <thead>
              <tr>
                <th />
                {arms.map((arm) => (
                  <th key={arm} colSpan={4}>{ARM_LABELS[arm] ?? arm}</th>
                ))}
              </tr>
              <tr className="jx-subhead">
                <th>Measurement</th>
                {arms.map((arm) => (
                  <Fragment key={arm}>
                    <th>est</th>
                    <th>map</th>
                    <th>app</th>
                    <th>protractor</th>
                  </Fragment>
                ))}
              </tr>
            </thead>
            <tbody>
              {measurements.map((m) => (
                <tr key={m.key}>
                  <td className="jx-measure">{m.label}</td>
                  {arms.map((arm) => (
                    <Fragment key={arm}>
                      <td className="jx-num">
                        {hasCapture ? fmt(shown?.est?.[arm]?.[m.key]) : '—'}
                      </td>
                      <td className={`jx-num ${clamped.has(`${arm}/${m.key}`) ? 'jx-clamped' : ''}`}>
                        {hasCapture ? fmt(shown?.mapped?.[arm]?.[m.key]) : '—'}
                        {clamped.has(`${arm}/${m.key}`) ? '*' : ''}
                      </td>
                      <td className="jx-num">
                        {hasCapture ? fmt(shown?.applied?.[arm]?.[m.key]) : '—'}
                      </td>
                      <td>
                        <input className="jx-input" inputMode="decimal"
                          value={draft[arm]?.[m.key] ?? ''}
                          onChange={(e) =>
                            setDraft({
                              ...draft,
                              [arm]: { ...draft[arm], [m.key]: e.target.value },
                            })
                          } />
                      </td>
                    </Fragment>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>

          <div className="jx-legend">
            est = estimator's view of you · map = retargeting output · app = pose after the safety
            layer · * = at a joint limit, the robot cannot reach the requested angle
          </div>

          <label className="jx-notes">Notes
            <input value={notes} onChange={(e) => setNotes(e.target.value)} />
          </label>

          <div className="jx-mode-line">
            leg mode <b>{legMode}</b> · {simOnly ? 'simulator only' : 'sim + physical robot'}
            {!dispatchMoves && ' · dispatch off'}
          </div>

          {status && <div className={`jx-status jx-${status.tone}`}>{status.text}</div>}
        </section>
      </main>
    </div>
  )
}
