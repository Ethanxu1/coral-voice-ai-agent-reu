import { useCallback, useEffect, useRef, useState } from 'react'

import RobotViewer from '../components/RobotViewer'
import { visionUpperBodyFeedUrl } from './api'
import type { MirrorPoseResult } from './types'

type MirrorStatus = 'preparing' | 'connecting' | 'tracking' | 'limited' | 'slowed' | 'blocked' | 'reframing'

const PREPARATION_DELAY_MS = 700

const mirrorCopy: Record<MirrorStatus, { label: string; detail: string }> = {
  preparing: {
    label: 'Preparing simulator…',
    detail: 'Returning to a balanced stand before mirroring begins.',
  },
  connecting: {
    label: 'Connecting to your pose…',
    detail: 'Keep your shoulders, elbows, and wrists visible.',
  },
  tracking: {
    label: 'Robot is following you',
    detail: 'Your upper-body arm pose is mirrored at a steady rate.',
  },
  limited: {
    label: 'Safety limited',
    detail: 'The simulator reduced this movement to prevent a collision.',
  },
  slowed: {
    label: 'Motion slowed',
    detail: 'The simulator is smoothing this movement to reduce the chance of a fall.',
  },
  blocked: {
    label: 'Unsafe pose blocked',
    detail: 'Return to a balanced standing pose to continue.',
  },
  reframing: {
    label: 'Upper body not visible',
    detail: 'Reframe so both shoulders, elbows, and wrists are visible.',
  },
}

export function RobotPoseCaptureWorkspace({
  open,
  name,
  cameraEnabled,
  onNameChange,
  onMirror,
  onCapture,
  onEnterCapture,
  onExitCapture,
  onResetSimulator,
  simulatorResetting,
  onClose,
}: {
  open: boolean
  name: string
  cameraEnabled: boolean
  onNameChange: (name: string) => void
  onMirror: (signal?: AbortSignal) => Promise<MirrorPoseResult>
  onCapture: (name: string, joints: Record<string, number>) => Promise<unknown>
  onEnterCapture: (sessionId: string) => Promise<void>
  onExitCapture: (sessionId: string) => Promise<void>
  onResetSimulator: () => Promise<boolean>
  simulatorResetting: boolean
  onClose: () => void
}) {
  const [capturing, setCapturing] = useState(false)
  const [preparing, setPreparing] = useState(true)
  const [ready, setReady] = useState(false)
  const [fallDetected, setFallDetected] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [latestSafePose, setLatestSafePose] = useState<Record<string, number> | null>(null)
  const [mirrorStatus, setMirrorStatus] = useState<MirrorStatus>('preparing')
  const [mirrorDetail, setMirrorDetail] = useState(mirrorCopy.preparing.detail)
  const nameInputRef = useRef<HTMLInputElement>(null)
  const wasSaved = useRef(false)
  const mirrorAbortRef = useRef<AbortController | null>(null)
  const stoppingForResetRef = useRef(false)
  const preparingRef = useRef(true)
  const preparationTimerRef = useRef<number | undefined>(undefined)
  const mirrorRetryTimerRef = useRef<number | undefined>(undefined)
  const preparationRunRef = useRef(0)
  const captureSessionsRef = useRef<Array<{
    id: string
    enterPromise: Promise<void>
  }>>([])

  const stopMirroring = useCallback(() => {
    stoppingForResetRef.current = true
    mirrorAbortRef.current?.abort()
    mirrorAbortRef.current = null
    if (mirrorRetryTimerRef.current !== undefined) {
      window.clearTimeout(mirrorRetryTimerRef.current)
      mirrorRetryTimerRef.current = undefined
    }
  }, [])

  const prepareSimulator = useCallback(async () => {
    const run = preparationRunRef.current + 1
    preparationRunRef.current = run
    stopMirroring()
    if (preparationTimerRef.current !== undefined) {
      window.clearTimeout(preparationTimerRef.current)
    }
    preparingRef.current = true
    setPreparing(true)
    setReady(false)
    setLatestSafePose(null)
    setMirrorStatus('preparing')
    setMirrorDetail(mirrorCopy.preparing.detail)
    setError(null)

    const sessionId = crypto.randomUUID()
    const enterCapturePromise = Promise.resolve().then(() => onEnterCapture(sessionId))
    captureSessionsRef.current.push({ id: sessionId, enterPromise: enterCapturePromise })
    try {
      await enterCapturePromise
    } catch (cause) {
      if (preparationRunRef.current !== run) return
      setPreparing(false)
      setMirrorStatus('blocked')
      setMirrorDetail(
        cause instanceof Error ? cause.message : 'Could not prepare upper-body tracking.',
      )
      return
    }

    const reset = await onResetSimulator()
    if (preparationRunRef.current !== run) return
    if (!reset) {
      setPreparing(false)
      setMirrorStatus('blocked')
      setMirrorDetail('Reset failed. Mirroring remains stopped for safety.')
      return
    }

    setFallDetected(false)
    preparationTimerRef.current = window.setTimeout(() => {
      if (preparationRunRef.current !== run) return
      preparingRef.current = false
      stoppingForResetRef.current = false
      setPreparing(false)
      setReady(true)
      setMirrorStatus('connecting')
      setMirrorDetail(mirrorCopy.connecting.detail)
    }, PREPARATION_DELAY_MS)
  }, [onEnterCapture, onResetSimulator, stopMirroring])

  useEffect(() => {
    if (wasSaved.current && !saved) nameInputRef.current?.focus()
    wasSaved.current = saved
  }, [saved])

  useEffect(() => {
    if (!open) return
    void prepareSimulator()
    return () => {
      preparationRunRef.current += 1
      stopMirroring()
      const captureSessions = captureSessionsRef.current
      for (const captureSession of captureSessions) {
        void captureSession.enterPromise
          .catch(() => undefined)
          .then(() => onExitCapture(captureSession.id))
      }
      if (preparationTimerRef.current !== undefined) {
        window.clearTimeout(preparationTimerRef.current)
      }
    }
  }, [onExitCapture, open, prepareSimulator, stopMirroring])

  useEffect(() => {
    if (!open || !cameraEnabled || saved || capturing || !ready || fallDetected) return

    let active = true
    let retryTimer: number | undefined
    let staleTimer: number | undefined
    let timeoutTimer: number | undefined
    let request: AbortController | undefined

    const mirror = async () => {
      if (!active || stoppingForResetRef.current) return
      request = new AbortController()
      mirrorAbortRef.current = request
      staleTimer = window.setTimeout(() => {
        if (!active) return
        setLatestSafePose(null)
        setMirrorStatus('connecting')
        setMirrorDetail('Waiting for a fresh, safety-checked pose.')
      }, 700)
      timeoutTimer = window.setTimeout(() => request?.abort(), 1_200)
      let retryDelay = 80
      try {
        const result = await onMirror(request.signal)
        if (!active) return
        if (result.status === 'blocked' || result.safety.fall_blocked) {
          setLatestSafePose(null)
          setMirrorStatus('blocked')
          setMirrorDetail(mirrorCopy.blocked.detail)
        } else {
          setLatestSafePose(result.targets)
          if (result.safety.collision_clamped) {
            setMirrorStatus('limited')
            setMirrorDetail(
              `Movement reduced to ${Math.round(result.safety.safe_fraction * 100)}% to prevent a collision.`,
            )
          } else if (result.safety.rate_limited) {
            setMirrorStatus('slowed')
            setMirrorDetail(mirrorCopy.slowed.detail)
          } else {
            setMirrorStatus('tracking')
            setMirrorDetail(mirrorCopy.tracking.detail)
          }
        }
      } catch (cause) {
        if (!active) return
        retryDelay = 600
        setLatestSafePose(null)
        setMirrorStatus('reframing')
        setMirrorDetail(
          cause instanceof DOMException && cause.name === 'AbortError'
            ? 'Pose tracking timed out. Check the camera and services.'
            : cause instanceof Error ? cause.message : mirrorCopy.reframing.detail,
        )
      } finally {
        if (mirrorAbortRef.current === request) mirrorAbortRef.current = null
        if (staleTimer !== undefined) window.clearTimeout(staleTimer)
        if (timeoutTimer !== undefined) window.clearTimeout(timeoutTimer)
      }
      if (active && !stoppingForResetRef.current) {
        retryTimer = window.setTimeout(() => void mirror(), retryDelay)
        mirrorRetryTimerRef.current = retryTimer
      }
    }

    setMirrorStatus('connecting')
    setMirrorDetail(mirrorCopy.connecting.detail)
    void mirror()

    return () => {
      active = false
      request?.abort()
      if (retryTimer !== undefined) window.clearTimeout(retryTimer)
      if (mirrorRetryTimerRef.current === retryTimer) {
        mirrorRetryTimerRef.current = undefined
      }
      if (staleTimer !== undefined) window.clearTimeout(staleTimer)
      if (timeoutTimer !== undefined) window.clearTimeout(timeoutTimer)
    }
  }, [cameraEnabled, capturing, fallDetected, onMirror, open, ready, saved])

  if (!open) return null

  const capture = async () => {
    if (!name.trim() || capturing || !latestSafePose) return
    setCapturing(true)
    setError(null)
    try {
      await onCapture(name.trim(), latestSafePose)
      setSaved(true)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not capture this pose')
    } finally {
      setCapturing(false)
    }
  }

  const addNew = () => {
    onNameChange('')
    setError(null)
    setLatestSafePose(null)
    setMirrorStatus('connecting')
    setMirrorDetail(mirrorCopy.connecting.detail)
    setSaved(false)
  }

  const handleStabilityChange = (fallen: boolean) => {
    if (!fallen || preparingRef.current || fallDetected) return
    stopMirroring()
    setReady(false)
    setLatestSafePose(null)
    setFallDetected(true)
    setMirrorStatus('blocked')
    setMirrorDetail('Press Reset Simulator before continuing.')
  }

  return (
    <div className="pose-capture-shell">
      <section
        className="pose-capture-workspace"
        role="dialog"
        aria-modal="true"
        aria-labelledby="pose-capture-title"
      >
        <header className="pose-capture-header">
          <div>
            <span className="studio-kicker">Human → safety check → simulator</span>
            <h2 id="pose-capture-title">Pose Capture</h2>
          </div>
          <button
            type="button"
            className="capture-close"
            onClick={onClose}
            disabled={capturing}
            aria-label="Close pose capture"
          >
            ×
          </button>
        </header>

        <div className="pose-capture-stage">
          <section className="capture-viewport capture-human" aria-label="Human pose preview">
            <span className="capture-viewport-label">You</span>
            {cameraEnabled ? (
              <img src={visionUpperBodyFeedUrl} alt="Live human pose" />
            ) : (
              <div className="capture-camera-off">
                <strong>Camera is off</strong>
                <small>Turn on the computer camera before capturing.</small>
              </div>
            )}
          </section>
          <section className="capture-viewport capture-robot" aria-label="Robot pose preview">
            <span className="capture-viewport-label">Robot simulator</span>
            <RobotViewer embedded onStabilityChange={handleStabilityChange} />
          </section>
        </div>

        <footer className="pose-capture-controls">
          <div className="capture-instruction">
            <strong>{saved ? 'Pose saved and shown in the simulator' : 'Match the pose you want the robot to remember'}</strong>
            <small>{saved ? 'Safety checks passed. Compare both views, then finish.' : 'Keep both shoulders, elbows, and wrists visible.'}</small>
            {!saved && cameraEnabled ? (
              <div
                className={`capture-mirror-status is-${mirrorStatus}`}
                role={fallDetected ? 'alert' : 'status'}
              >
                <i aria-hidden="true" />
                <span>
                  <b>{fallDetected ? 'Fall detected — mirroring stopped' : mirrorCopy[mirrorStatus].label}</b>
                  <small>{mirrorDetail}</small>
                </span>
              </div>
            ) : null}
          </div>
          {error ? <p className="capture-error" role="alert">{error}</p> : null}
          <label>
            Robot pose name
            <input
              ref={nameInputRef}
              value={name}
              onChange={(event) => onNameChange(event.target.value)}
              disabled={capturing || saved}
              autoFocus
            />
          </label>
          {saved ? (
            <>
              <button type="button" className="studio-secondary-button" onClick={addNew}>Add New</button>
              <button type="button" className="studio-primary-button" onClick={onClose}>Done</button>
            </>
          ) : (
            <>
              <button
                type="button"
                className="studio-secondary-button"
                disabled={capturing || simulatorResetting || preparing}
                onPointerDown={stopMirroring}
                onClick={() => void prepareSimulator()}
                aria-label="Reset Simulator"
              >
                {simulatorResetting || preparing ? 'Resetting…' : 'Reset Simulator'}
              </button>
              <button
                type="button"
                className="studio-ghost-button"
                onClick={onClose}
                disabled={capturing}
              >
                Cancel
              </button>
              <button
                type="button"
                className="studio-primary-button"
                disabled={!name.trim() || capturing || !cameraEnabled || !latestSafePose || !ready || fallDetected}
                onClick={() => void capture()}
              >
                {capturing ? 'Checking…' : 'Capture & Safety Check'}
              </button>
            </>
          )}
        </footer>
      </section>
    </div>
  )
}
