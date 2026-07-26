import { useCallback, useEffect, useRef, useState } from 'react'
import { usePoseWebSocket } from '../hooks/usePoseWebSocket'
import CameraFeed from '../components/pose/CameraFeed'
import type { TuningParamSpec } from '../types/pose'

const STATUS_TEXT: Record<string, string> = {
  idle: 'Press Start to begin subject selection',
  selecting: 'Raise one hand above your head for 3 seconds to select a subject',
  selected: 'Subject locked — tracking selected subject',
  searching: 'Subject lost — searching…',
}

const PATH_COLORS: Record<string, string> = {
  fused: '#4ade80',
  face: '#60a5fa',
  appearance: '#f59e0b',
  legacy: '#a78bfa',
  none: '#666',
}

function fmt(n: number | null | undefined, digits = 3): string {
  return typeof n === 'number' && Number.isFinite(n) ? n.toFixed(digits) : '—'
}

export default function SubjectSelect() {
  const {
    isConnected,
    selectionState,
    selectedSubjectId,
    subjects,
    startSelection,
    resetSelection,
    stopSelection,
    fetchTuning,
    updateTuning,
  } = usePoseWebSocket()

  const [tuningParams, setTuningParams] = useState<TuningParamSpec[]>([])
  const [tuningValues, setTuningValues] = useState<Record<string, number>>({})
  const [initialValues, setInitialValues] = useState<Record<string, number>>({})
  const updateTimers = useRef<Record<string, number>>({})

  useEffect(() => {
    startSelection()
    return () => {
      stopSelection()
    }
  }, [startSelection, stopSelection])

  useEffect(() => {
    // Load current backend tuning once — subsequent state stays in local
    // React state and is pushed to the backend on slider change.
    fetchTuning()
      .then((data) => {
        setTuningParams(data.params ?? [])
        setTuningValues(data.values ?? {})
        setInitialValues(data.values ?? {})
      })
      .catch((err) => console.warn('tuning fetch failed', err))
  }, [fetchTuning])

  const pushValue = useCallback(
    (key: string, value: number) => {
      // Debounce per-key updates so dragging a slider doesn't spam the API.
      setTuningValues((prev) => ({ ...prev, [key]: value }))
      window.clearTimeout(updateTimers.current[key])
      updateTimers.current[key] = window.setTimeout(() => {
        updateTuning({ [key]: value }).catch((err) => console.warn('tuning update failed', err))
      }, 80)
    },
    [updateTuning],
  )

  const resetTuning = useCallback(() => {
    setTuningValues({ ...initialValues })
    updateTuning(initialValues).catch((err) => console.warn('tuning reset failed', err))
  }, [initialValues, updateTuning])

  const selectedMetrics = subjects.find((s) => s.id === selectedSubjectId)?.metrics ?? null

  return (
    <div style={{
      minHeight: '100vh',
      background: '#111',
      color: '#eee',
      fontFamily: 'system-ui, sans-serif',
      padding: 16,
      boxSizing: 'border-box',
    }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <a href="/" style={{ color: '#888', fontSize: 13, textDecoration: 'none' }}>← Back</a>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 600 }}>Subject Select — Tuning</h2>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{
            width: 8, height: 8, borderRadius: '50%',
            background: isConnected ? '#0f0' : '#f00',
          }} />
          <span style={{ fontSize: 12, color: '#888' }}>{isConnected ? 'Connected' : 'Disconnected'}</span>
        </div>
      </div>

      {/* Status banner */}
      <div style={{
        marginBottom: 16,
        padding: '12px 16px',
        borderRadius: 8,
        background: selectionState === 'selected' ? '#0a2a10'
          : selectionState === 'searching' ? '#2a1a00'
          : '#1a1a2e',
        border: `1px solid ${
          selectionState === 'selected' ? '#2f4'
            : selectionState === 'searching' ? '#f90'
            : '#44f'
        }`,
      }}>
        <div style={{ fontSize: 14, fontWeight: 500 }}>{STATUS_TEXT[selectionState] ?? STATUS_TEXT.idle}</div>
        <div style={{ fontSize: 12, color: '#888', marginTop: 4 }}>
          Selected: <span style={{ color: '#eee' }}>{selectedSubjectId ?? '—'}</span>
          {'  '}·{'  '}Path: <span style={{ color: PATH_COLORS[selectedMetrics?.path ?? 'none'] }}>
            {selectedMetrics?.path ?? '—'}
          </span>
          {'  '}·{'  '}Score: <span style={{ color: '#eee' }}>{fmt(selectedMetrics?.score, 3)}</span>
        </div>
      </div>

      {/* Camera + metrics side-by-side */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
        {/* Camera feed */}
        <div>
          <div style={{ fontSize: 12, color: '#666', marginBottom: 6 }}>
            Camera {selectionState === 'selecting' ? `(detected: ${subjects.length})` : ''}
          </div>
          <div style={{ aspectRatio: '4/3', background: '#111', borderRadius: 8, overflow: 'hidden' }}>
            <CameraFeed />
          </div>
        </div>

        {/* Metrics table */}
        <div>
          <div style={{ fontSize: 12, color: '#666', marginBottom: 6 }}>
            Per-subject match metrics
          </div>
          <div style={{
            background: '#0d0d0d', border: '1px solid #222', borderRadius: 8, padding: 12,
            fontSize: 12, fontFamily: 'ui-monospace, monospace',
          }}>
            {subjects.length === 0 ? (
              <div style={{ color: '#666' }}>No subjects detected</div>
            ) : (
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ color: '#888', textAlign: 'left' }}>
                    <th style={{ paddingBottom: 6 }}>id</th>
                    <th>face</th>
                    <th>det</th>
                    <th>app</th>
                    <th>score</th>
                    <th>path</th>
                    <th>ok</th>
                  </tr>
                </thead>
                <tbody>
                  {subjects.map((s) => {
                    const m = s.metrics
                    const isSel = s.id === selectedSubjectId
                    return (
                      <tr key={s.id} style={{
                        background: isSel ? '#0a2a10' : 'transparent',
                        color: isSel ? '#dfffe0' : '#ddd',
                      }}>
                        <td style={{ padding: '4px 6px 4px 0' }}>
                          {isSel ? '★ ' : ''}{s.id}
                        </td>
                        <td>{fmt(m?.face_sim)}</td>
                        <td>{fmt(m?.face_det_score, 2)}</td>
                        <td>{fmt(m?.app_sim)}</td>
                        <td style={{ fontWeight: 600 }}>{fmt(m?.score)}</td>
                        <td style={{ color: PATH_COLORS[m?.path ?? 'none'] }}>{m?.path ?? '—'}</td>
                        <td>{m?.passed ? '✓' : '·'}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
            <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid #222', color: '#666', fontSize: 11, lineHeight: 1.5 }}>
              <b style={{ color: '#888' }}>face</b> = cosine sim vs face anchor ·{' '}
              <b style={{ color: '#888' }}>det</b> = SCRFD detector confidence ·{' '}
              <b style={{ color: '#888' }}>app</b> = HSV histogram intersection ·{' '}
              <b style={{ color: '#888' }}>score</b> = value gated by <b>path</b> (fused / face / appearance) ·{' '}
              <b style={{ color: '#888' }}>ok</b> = passes that path's threshold
            </div>
          </div>
        </div>
      </div>

      {/* Controls */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
        <button
          onClick={startSelection}
          style={{ padding: '8px 16px', borderRadius: 6, border: 'none', background: '#4f46e5', color: '#fff', cursor: 'pointer', fontSize: 14 }}
        >
          Start Selection
        </button>
        <button
          onClick={resetSelection}
          style={{ padding: '8px 16px', borderRadius: 6, border: '1px solid #555', background: '#222', color: '#eee', cursor: 'pointer', fontSize: 14 }}
        >
          Reset
        </button>
        <button
          onClick={resetTuning}
          style={{ padding: '8px 16px', borderRadius: 6, border: '1px solid #555', background: '#222', color: '#eee', cursor: 'pointer', fontSize: 14, marginLeft: 'auto' }}
        >
          Reset tuning to defaults
        </button>
      </div>

      {/* Tuning sliders */}
      <div style={{
        background: '#0d0d0d', border: '1px solid #222', borderRadius: 8, padding: 16,
      }}>
        <div style={{ fontSize: 13, color: '#eee', fontWeight: 600, marginBottom: 8 }}>Live tuning</div>
        <div style={{ fontSize: 11, color: '#666', marginBottom: 12 }}>
          Changes apply immediately to the running vision loop. No restart needed. Watch the metrics table above as you drag.
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          {tuningParams.map((p) => {
            const val = tuningValues[p.key] ?? p.min
            return (
              <div key={p.key} style={{ padding: '8px 10px', border: '1px solid #222', borderRadius: 6 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4 }}>
                  <span style={{ color: '#ccc' }}>{p.label}</span>
                  <span style={{ color: '#eee', fontFamily: 'ui-monospace, monospace' }}>{val.toFixed(3)}</span>
                </div>
                <input
                  type="range"
                  min={p.min}
                  max={p.max}
                  step={p.step}
                  value={val}
                  onChange={(e) => pushValue(p.key, Number(e.target.value))}
                  style={{ width: '100%' }}
                />
                <div style={{ fontSize: 10, color: '#666', marginTop: 4 }}>{p.hint}</div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
