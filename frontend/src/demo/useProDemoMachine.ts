// Simplified "pro" demo machine — a stripped-down sibling of useDemoMachine
// meant for demonstrating functionality (not the kids experience). No speaker,
// no intro/outro, no coaching pages. Flow, repeated 3×:
//   WATCH (live stream, wait for arms-crossed) → COUNTDOWN → LOADING (map-features)
//   → ADJUST (voice/text) → NAME → next loop; then DONE shows the named moves.

import { useCallback, useEffect, useReducer, useRef } from 'react'
import {
  captureUtterance,
  mapFeatures,
  move,
  openActionSession,
  playShutter,
  sendAudioForTranscript,
  setRobotState,
  sleep,
  watchForAction,
} from './api'
import { LOOP_COUNT, WATCH_TIMEOUT_S } from './config'

export type ProStage =
  | 'IDLE'
  | 'WATCH'
  | 'COUNTDOWN'
  | 'LOADING'
  | 'ADJUST'
  | 'NAME'
  | 'DONE'
  | 'ERROR'

export type ProStatus = 'idle' | 'recording' | 'thinking' | 'action' | 'clarify'
export type InputMode = 'voice' | 'text'

/** A captured + named move: the label plus the frame it was read from. */
export interface ProMove {
  name: string
  frame: string | null
}

export interface ProState {
  stage: ProStage
  loop: number
  totalLoops: number
  countdown: number | null
  flash: boolean
  status: ProStatus
  caption: string
  /** Retake hint shown when the pose couldn't be mapped (hips out of frame). */
  detail: string | null
  /** Most recent captured frame (base64 JPEG, no data: prefix). */
  frame: string | null
  awaitingText: boolean
  inputMode: InputMode
  moves: ProMove[]
  error: string | null
  /** Live mic RMS during voice capture (0 when not recording). */
  micLevel: number
  /** Last user utterance (voice transcription or typed text) — shown to the user for verification. */
  lastTranscript: string | null
  /** Agent's most recent verbal_response — persists so the user can read it while the next turn is being captured. */
  lastResponse: string | null
}

const initialState: ProState = {
  stage: 'IDLE',
  loop: 0,
  totalLoops: LOOP_COUNT,
  countdown: null,
  flash: false,
  status: 'idle',
  caption: '',
  detail: null,
  frame: null,
  awaitingText: false,
  inputMode: 'voice',
  moves: [],
  error: null,
  micLevel: 0,
  lastTranscript: null,
  lastResponse: null,
}

function reducer(state: ProState, patch: Partial<ProState>): ProState {
  return { ...state, ...patch }
}

const CANCELLED = Symbol('cancelled')
const MAX_RETAKES = 3

export function useProDemoMachine() {
  const [state, dispatch] = useReducer(reducer, initialState)
  const tokenRef = useRef(0)
  const inputModeRef = useRef<InputMode>('voice')
  const textResolverRef = useRef<((value: string) => void) | null>(null)

  useEffect(() => () => { tokenRef.current++ }, []) // abort on unmount

  const awaitText = useCallback(
    () => new Promise<string>((resolve) => { textResolverRef.current = resolve }),
    [],
  )

  const submitText = useCallback((text: string) => {
    const resolve = textResolverRef.current
    textResolverRef.current = null
    dispatch({ awaitingText: false })
    resolve?.(text)
  }, [])

  const toggleInputMode = useCallback(() => {
    inputModeRef.current = inputModeRef.current === 'voice' ? 'text' : 'voice'
    dispatch({ inputMode: inputModeRef.current })
  }, [])

  const run = useCallback(async () => {
    const token = ++tokenRef.current
    const active = () => { if (tokenRef.current !== token) throw CANCELLED }

    dispatch({ ...initialState, inputMode: inputModeRef.current, stage: 'WATCH' })

    try {
      const moves: ProMove[] = []

      for (let i = 0; i < state.totalLoops; i++) {
        // ── WATCH: live stream, wait for the arms-crossed go-ahead ────────────
        dispatch({
          stage: 'WATCH',
          loop: i,
          countdown: null,
          flash: false,
          status: 'idle',
          frame: null,
          detail: null,
          caption: 'Cross your arms to capture a pose',
        })
        let detected = false
        while (!detected) {
          active()
          detected = (await watchSafely()).detected
        }

        // ── COUNTDOWN + LOADING: snap, then map-features (retake if no hips) ──
        let mapped = null
        for (let take = 0; take < MAX_RETAKES && mapped === null; take++) {
          await setRobotState('DEMO_LOCKED'); active()
          dispatch({ stage: 'COUNTDOWN', caption: 'Hold your pose', detail: null })
          for (const n of [3, 2, 1]) {
            dispatch({ countdown: n })
            await sleep(1000); active()
          }
          dispatch({ countdown: null, flash: true, stage: 'LOADING', caption: 'Analyzing pose…' })
          playShutter()
          const result = await mapFeatures(); active()
          dispatch({ flash: false })
          if (result.poseDetected) {
            mapped = result
            dispatch({ frame: result.imageB64 })
            await move(result.commands).catch(() => {}); active()
          } else {
            dispatch({ stage: 'WATCH', detail: result.detail, caption: 'Let\'s try that again' })
            await sleep(2200); active()
          }
        }
        await setRobotState('IDLE'); active()

        if (mapped === null) {
          dispatch({ stage: 'ERROR', error: 'Couldn\'t read a full-body pose after several tries.' })
          return
        }

        // ── ADJUST: loop until the user says they're satisfied ──
        // One WebSocket for the whole refinement so the server's per-connection
        // HierarchicalMemory + Langfuse session_id span every turn — otherwise
        // each utterance would look like a stateless first message to the LLM.
        const session = openActionSession()
        // Reset the mini-conversation for this pose. Subsequent turns intentionally
        // leave lastTranscript / lastResponse alone so the user can still read the
        // prior exchange while the next input is being captured.
        dispatch({ lastTranscript: null, lastResponse: null })
        try {
          let satisfied = false
          let firstTurn = true
          while (!satisfied) {
            active()
            const promptCaption = firstTurn
              ? 'Describe an adjustment'
              : 'Any more adjustments? Say "looks good" when done'
            const listenCaption = firstTurn
              ? 'Listening — describe an adjustment'
              : 'Listening — more tweaks, or say "looks good"'

            let result
            if (inputModeRef.current === 'text') {
              dispatch({ stage: 'ADJUST', status: 'idle', awaitingText: true, caption: promptCaption })
              const text = await awaitText(); active()
              dispatch({ awaitingText: false, status: 'thinking', caption: 'Thinking…', lastTranscript: text })
              result = await session.sendText(text); active()
            } else {
              dispatch({ stage: 'ADJUST', status: 'recording', caption: listenCaption, micLevel: 0 })
              const blob = await captureUtterance({
                onLevel: (rms) => dispatch({ micLevel: rms }),
              }); active()
              dispatch({ status: 'thinking', caption: 'Transcribing…', micLevel: 0 })
              result = await session.sendAudio(blob); active()
              dispatch({ lastTranscript: result.transcript || '(no speech detected)' })
            }
            dispatch({ lastResponse: result.content || null })
            firstTurn = false

            if (result.satisfied === true) {
              // Combined case: apply any final tweak that came with the "done" signal.
              if (result.hasAction) {
                dispatch({ status: 'action', caption: result.content || 'Adjustment applied' })
                await sleep(1200); active()
              }
              satisfied = true
              dispatch({ status: 'idle', caption: result.content || 'Locked in' })
              await sleep(600); active()
            } else if (result.hasAction) {
              dispatch({ status: 'action', caption: result.content || 'Adjustment applied' })
              await sleep(1400); active()
            } else {
              dispatch({ status: 'clarify', caption: result.content || 'Didn\'t catch that — try rephrasing' })
              await sleep(1600); active()
            }
          }
        } finally {
          session.close()
        }

        // ── NAME: label this move ────────────────────────────────────────────
        // Clear the ADJUST mini-conversation so it doesn't sit over the NAME prompt.
        let label: string
        if (inputModeRef.current === 'text') {
          dispatch({ stage: 'NAME', status: 'idle', awaitingText: true, caption: 'Name this move', lastTranscript: null, lastResponse: null })
          label = (await awaitText()); active()
          dispatch({ awaitingText: false, status: 'thinking', lastTranscript: label })
        } else {
          dispatch({ stage: 'NAME', status: 'recording', caption: 'Say a name for this move', lastTranscript: null, lastResponse: null, micLevel: 0 })
          const nameBlob = await captureUtterance({
            onLevel: (rms) => dispatch({ micLevel: rms }),
          }); active()
          dispatch({ status: 'thinking', caption: 'Transcribing…', micLevel: 0 })
          label = await sendAudioForTranscript(nameBlob); active()
          dispatch({ lastTranscript: label || '(no speech detected)' })
        }
        const name = label.trim() || `Move ${i + 1}`
        moves.push({ name, frame: mapped.imageB64 })
        dispatch({ moves: [...moves], status: 'idle' })
      }

      dispatch({ stage: 'DONE', moves: [...moves], caption: 'Session complete' })
    } catch (err) {
      if (err === CANCELLED) return
      dispatch({ stage: 'ERROR', error: String(err) })
    }
  }, [state.totalLoops])

  const exit = useCallback(() => {
    tokenRef.current++
    textResolverRef.current?.('')
    textResolverRef.current = null
    setRobotState('IDLE')
    dispatch({ ...initialState, inputMode: inputModeRef.current })
  }, [])

  return { state, start: run, retry: run, exit, toggleInputMode, submitText }
}

async function watchSafely(): Promise<{ detected: boolean }> {
  try {
    return await watchForAction(WATCH_TIMEOUT_S)
  } catch {
    return { detected: false }
  }
}
