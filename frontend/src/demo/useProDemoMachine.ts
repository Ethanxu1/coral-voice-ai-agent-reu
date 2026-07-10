// Simplified "pro" demo machine. Flow:
//   Start → ADJUST (conversational — user speaks freely, captures when ready)
//   → COUNTDOWN → LOADING → ADJUST (post-capture refinement) → NAME → repeat → DONE

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
} from './api'
import { LOOP_COUNT } from './config'

export type ProStage =
  | 'IDLE'
  | 'COUNTDOWN'
  | 'LOADING'
  | 'ADJUST'
  | 'NAME'
  | 'DONE'
  | 'ERROR'

export type ProStatus = 'idle' | 'recording' | 'thinking' | 'action' | 'clarify'
export type InputMode = 'voice' | 'text'

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
  detail: string | null
  frame: string | null
  awaitingText: boolean
  inputMode: InputMode
  moves: ProMove[]
  error: string | null
  micLevel: number
  lastTranscript: string | null
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

// Detect when the user wants to trigger a pose capture.
const CAPTURE_RE = /\b(capture|take a (photo|picture|snapshot)|photograph|snap this|(capture|take|snap) (my |this )?(pose|position))\b/i

export function useProDemoMachine() {
  const [state, dispatch] = useReducer(reducer, initialState)
  const tokenRef = useRef(0)
  const inputModeRef = useRef<InputMode>('voice')
  const textResolverRef = useRef<((value: string) => void) | null>(null)

  useEffect(() => () => { tokenRef.current++ }, [])

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

    dispatch({
      ...initialState,
      inputMode: inputModeRef.current,
      stage: 'ADJUST',
      lastResponse: "Hi! What would you like me to do?",
    })

    try {
      const moves: ProMove[] = []

      for (let i = 0; i < state.totalLoops; i++) {
        dispatch({ loop: i, frame: null, detail: null })

        // ── Open one session per loop so memory spans pre- and post-capture ──
        const session = openActionSession()

        try {
          // ── PRE-CAPTURE: listen freely until user says "capture [my] pose" ──
          let captureRequested = false
          while (!captureRequested) {
            active()
            let transcript: string

            if (inputModeRef.current === 'text') {
              dispatch({ stage: 'ADJUST', status: 'idle', awaitingText: true, caption: '' })
              transcript = await awaitText(); active()
              dispatch({ awaitingText: false, lastTranscript: transcript })
            } else {
              dispatch({ stage: 'ADJUST', status: 'recording', caption: 'Listening…', micLevel: 0 })
              const blob = await captureUtterance({ onLevel: (rms) => dispatch({ micLevel: rms }) }); active()
              dispatch({ status: 'thinking', caption: 'Transcribing…', micLevel: 0 })
              transcript = await sendAudioForTranscript(blob); active()
              dispatch({ lastTranscript: transcript || '(no speech detected)', micLevel: 0 })
            }

            if (CAPTURE_RE.test(transcript)) {
              captureRequested = true
            } else if (transcript.trim()) {
              dispatch({ status: 'thinking', caption: 'Thinking…' })
              const result = await session.sendText(transcript); active()
              dispatch({ lastResponse: result.content || null, caption: '' })
              if (result.hasAction) {
                dispatch({ status: 'action' })
                await sleep(1200); active()
              }
              dispatch({ status: 'idle' })
            } else {
              dispatch({ status: 'idle', caption: '' })
            }
          }

          // ── COUNTDOWN + LOADING ─────────────────────────────────────────────
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
              dispatch({ stage: 'ADJUST', frame: result.imageB64 })
              await move(result.commands).catch(() => {}); active()
            } else {
              dispatch({
                stage: 'ADJUST', detail: result.detail,
                lastResponse: result.detail || "Couldn't capture clearly — try again!",
              })
              await sleep(2000); active()
              dispatch({ detail: null })
            }
          }
          await setRobotState('IDLE'); active()

          if (mapped === null) {
            dispatch({ stage: 'ERROR', error: "Couldn't read a full-body pose after several tries." })
            return
          }

          dispatch({ lastTranscript: null, lastResponse: "Got it! How would you like to adjust this pose?" })

          // ── POST-CAPTURE ADJUST: refine until satisfied ─────────────────────
          let satisfied = false
          let firstTurn = true
          while (!satisfied) {
            active()
            let transcript: string

            if (inputModeRef.current === 'text') {
              const caption = firstTurn
                ? 'Describe an adjustment'
                : 'Any more adjustments? Say "looks good" when done'
              dispatch({ stage: 'ADJUST', status: 'idle', awaitingText: true, caption })
              transcript = await awaitText(); active()
              dispatch({ awaitingText: false, status: 'thinking', caption: 'Thinking…', lastTranscript: transcript })
              const result = await session.sendText(transcript); active()
              dispatch({ lastResponse: result.content || null })
              firstTurn = false

              if (result.satisfied === true) {
                if (result.hasAction) { dispatch({ status: 'action' }); await sleep(1200); active() }
                satisfied = true
                dispatch({ status: 'idle', caption: '' })
                await sleep(600); active()
              } else if (result.hasAction) {
                dispatch({ status: 'action' })
                await sleep(1400); active()
              } else {
                dispatch({ status: 'clarify' })
                await sleep(1600); active()
              }
            } else {
              const caption = firstTurn
                ? 'Listening — describe an adjustment'
                : 'Listening — more tweaks, or say "looks good"'
              dispatch({ stage: 'ADJUST', status: 'recording', caption, micLevel: 0 })
              const blob = await captureUtterance({ onLevel: (rms) => dispatch({ micLevel: rms }) }); active()
              dispatch({ status: 'thinking', caption: 'Transcribing…', micLevel: 0 })
              transcript = await sendAudioForTranscript(blob); active()
              dispatch({ lastTranscript: transcript || '(no speech detected)', micLevel: 0 })
              const result = await session.sendText(transcript); active()
              dispatch({ lastResponse: result.content || null })
              firstTurn = false

              if (result.satisfied === true) {
                if (result.hasAction) { dispatch({ status: 'action' }); await sleep(1200); active() }
                satisfied = true
                dispatch({ status: 'idle', caption: '' })
                await sleep(600); active()
              } else if (result.hasAction) {
                dispatch({ status: 'action' })
                await sleep(1400); active()
              } else {
                dispatch({ status: 'clarify' })
                await sleep(1600); active()
              }
            }
          }

          // ── NAME ────────────────────────────────────────────────────────────
          let label: string
          if (inputModeRef.current === 'text') {
            dispatch({ stage: 'NAME', status: 'idle', awaitingText: true, caption: 'Name this move', lastTranscript: null, lastResponse: null })
            label = await awaitText(); active()
            dispatch({ awaitingText: false, lastTranscript: label })
          } else {
            dispatch({ stage: 'NAME', status: 'recording', caption: 'Say a name for this move', lastTranscript: null, lastResponse: null, micLevel: 0 })
            const nameBlob = await captureUtterance({ onLevel: (rms) => dispatch({ micLevel: rms }) }); active()
            dispatch({ status: 'thinking', caption: 'Transcribing…', micLevel: 0 })
            label = await sendAudioForTranscript(nameBlob); active()
            dispatch({ lastTranscript: label || '(no speech detected)' })
          }
          const name = label.trim() || `Move ${i + 1}`
          moves.push({ name, frame: mapped.imageB64 })
          dispatch({
            moves: [...moves], status: 'idle', stage: 'ADJUST', frame: null,
            lastTranscript: null,
            lastResponse: i + 1 < state.totalLoops
              ? `Saved "${name}"! Say what you'd like, or say "capture my pose" for the next one.`
              : null,
          })

        } finally {
          session.close()
        }
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
