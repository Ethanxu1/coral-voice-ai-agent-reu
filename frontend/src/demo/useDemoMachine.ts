// Director demo state machine.
//
// Display state lives in a useReducer (serializable, drives the UI). The actual
// pipeline is an async runner that awaits each step in order and dispatches PATCH
// updates as it goes. No Redux / external store — just local state + refs.

import { useCallback, useEffect, useReducer, useRef } from 'react'
import {
  captureUtterance,
  classify,
  motion,
  playShutter,
  sendAudioForAction,
  setRobotState,
  sleep,
  speak,
  watchForAction,
  type ClassifyResult,
} from './api'
import { LOOP_COUNT, WATCH_TIMEOUT_S } from './config'

export type Stage =
  | 'IDLE'
  | 'INTRO'
  | 'CLASSIFY'
  | 'RECORD'
  | 'OUTRO'
  | 'DONE'
  | 'TIMEOUT'
  | 'ERROR'

export type RecordStatus = 'idle' | 'recording' | 'thinking' | 'action' | 'clarify'

export interface DemoState {
  stage: Stage
  loop: number
  totalLoops: number
  speaking: boolean
  countdown: number | null
  flash: boolean
  classifying: boolean
  classifyResult: ClassifyResult | null
  recording: boolean
  recordStatus: RecordStatus
  caption: string
  error: string | null
}

const initialState: DemoState = {
  stage: 'IDLE',
  loop: 0,
  totalLoops: LOOP_COUNT,
  speaking: false,
  countdown: null,
  flash: false,
  classifying: false,
  classifyResult: null,
  recording: false,
  recordStatus: 'idle',
  caption: '',
  error: null,
}

function reducer(state: DemoState, patch: Partial<DemoState>): DemoState {
  return { ...state, ...patch }
}

// Thrown internally to unwind the runner when the user exits/restarts.
const CANCELLED = Symbol('cancelled')

export function useDemoMachine() {
  const [state, dispatch] = useReducer(reducer, initialState)
  // Each run gets a token; if the active token changes mid-flight the runner aborts.
  const tokenRef = useRef(0)

  useEffect(() => () => { tokenRef.current++ }, []) // abort on unmount

  const run = useCallback(async () => {
    const token = ++tokenRef.current
    const active = () => { if (tokenRef.current !== token) throw CANCELLED }

    dispatch({ ...initialState, stage: 'INTRO', caption: 'Say hello to Coral!' })

    try {
      // ── INTRO ───────────────────────────────────────────────────────────────
      dispatch({ speaking: true, caption: 'Coral is introducing herself…' })
      await speak({ script: 'INTRO' }); active()
      dispatch({ speaking: false, caption: 'Coral waves hello! 👋' })
      await motion('wave'); active()
      dispatch({ caption: 'Cross your hands in front of you when you are ready!' })
      const { detected } = await watchSafely(); active()
      if (!detected) {
        dispatch({ stage: 'TIMEOUT', caption: 'I didn’t see the go-ahead. Try again or exit?' })
        return
      }

      // ── LOOP: CLASSIFY → RECORD ──────────────────────────────────────────────
      for (let i = 0; i < state.totalLoops; i++) {
        // CLASSIFY
        dispatch({ stage: 'CLASSIFY', loop: i, classifyResult: null, classifying: false })
        dispatch({ speaking: true, caption: 'Get into your pose!' })
        await speak({ script: i === 0 ? 'CLASSIFY_FIRST' : 'CLASSIFY_REPEAT' }); active()
        dispatch({ speaking: false })

        await setRobotState('DEMO_LOCKED'); active()

        // 3-2-1 countdown: each digit advances only after its audio returns.
        for (const n of [3, 2, 1]) {
          dispatch({ countdown: n })
          await speak({ script: String(n) }); active()
          if (n > 1) { await sleep(800); active() }
        }
        dispatch({ countdown: null, flash: true, classifying: true, caption: '📸 Snap!' })
        playShutter()
        const result = await classify(); active()
        dispatch({
          flash: false,
          classifying: false,
          classifyResult: result,
          caption: `I think that’s a ${prettyClass(result.className)}!`,
        })
        await sleep(2000); active()
        await motion(result.className).catch(() => {}); active() // mimic the detected pose
        await sleep(1500); active()
        await motion('stand'); active()
        await setRobotState('IDLE'); active()

        // RECORD
        dispatch({ stage: 'RECORD', recordStatus: 'idle', caption: '' })
        dispatch({ speaking: true })
        await speak({ script: 'RECORD' }); active()
        dispatch({ speaking: false })
        await sleep(1000); active()

        let gotAction = false
        while (!gotAction) {
          active()
          dispatch({ recording: true, recordStatus: 'recording', caption: 'I’m listening… 🎤' })
          const blob = await captureUtterance(); active()
          dispatch({ recording: false, recordStatus: 'thinking', caption: 'Hmm, let me think… 🤔' })
          const result2 = await sendAudioForAction(blob); active()
          if (result2.hasAction) {
            gotAction = true
            dispatch({ recordStatus: 'action', caption: result2.content || 'Got it! Watch me try!' })
          } else {
            dispatch({
              recordStatus: 'clarify',
              caption: result2.content || 'I didn’t quite catch that — tell me again!',
            })
            await sleep(1800); active()
          }
        }

        // The voice pipeline already moved the robot; hold, then return to stand.
        await sleep(2000); active()
        await motion('stand').catch(() => {}); active()
      }

      // ── OUTRO ────────────────────────────────────────────────────────────────
      dispatch({ stage: 'OUTRO', speaking: true, caption: 'How did Coral learn this?' })
      await speak({ script: 'OUTRO' }); active()
      await speak({ script: 'THANK_YOU' }); active()
      dispatch({ stage: 'DONE', speaking: false, caption: 'Thanks for playing with Coral! 🎉' })
    } catch (err) {
      if (err === CANCELLED) return
      dispatch({ stage: 'ERROR', error: String(err), caption: 'Something went wrong.' })
    }
  }, [state.totalLoops])

  const exit = useCallback(() => {
    tokenRef.current++ // abort any in-flight run
    setRobotState('IDLE')
    dispatch({ ...initialState })
  }, [])

  return { state, start: run, retry: run, exit }
}

// watch-for-action, but a network failure shouldn't crash the demo — treat it as
// "not detected" so the UI can offer retry/exit.
async function watchSafely(): Promise<{ detected: boolean }> {
  try {
    return await watchForAction(WATCH_TIMEOUT_S)
  } catch {
    return { detected: false }
  }
}

function prettyClass(name: string): string {
  return name.replace(/[-_]/g, ' ')
}
