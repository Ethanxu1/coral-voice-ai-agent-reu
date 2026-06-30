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
  sendAudioForTranscript,
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
  | 'NAME'
  | 'OUTRO'
  | 'DONE'
  | 'TIMEOUT'
  | 'ERROR'

export type RecordStatus = 'idle' | 'recording' | 'thinking' | 'action' | 'clarify'

export interface DemoState {
  stage: Stage
  /** 1-8: which TestUI page to display */
  page: number
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
  /** Name the child gave this loop's pose (set on NAME stage). */
  poseName: string | null
  /** Running list of all pose names collected across loops (for OUTRO display). */
  poseNames: string[]
}

const initialState: DemoState = {
  stage: 'IDLE',
  page: 1,
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
  poseName: null,
  poseNames: [],
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

    dispatch({ ...initialState, stage: 'INTRO', page: 1, caption: 'Say hello to Coral!' })

    try {
      // ── INTRO (page 1) ──────────────────────────────────────────────────────
      dispatch({ speaking: true, caption: 'Coral is introducing herself…' })
      await speak({ script: 'INTRO' }); active()
      dispatch({ speaking: false, caption: 'Coral waves hello! 👋' })
      await motion('wave'); active()

      // ── LOOP: (page 2 coaching → CLASSIFY → RECORD → NAME) × N ─────────────
      const accumulatedNames: string[] = []

      for (let i = 0; i < state.totalLoops; i++) {
        // Page 2 — classify coaching + wait for go-ahead gesture
        dispatch({
          stage: 'INTRO',
          page: 2,
          loop: i,
          speaking: true,
          caption: 'Get into your pose!',
        })
        await speak({ script: i === 0 ? 'CLASSIFY_FIRST' : 'CLASSIFY_REPEAT' }); active()
        dispatch({ speaking: false, caption: 'Cross your hands in front of you when you are ready!' })
        const { detected } = await watchSafely(); active()
        if (!detected) {
          dispatch({ stage: 'TIMEOUT', caption: 'I didn\'t see the go-ahead. Try again or exit?' })
          return
        }

        // ── CLASSIFY (page 3) ────────────────────────────────────────────────
        dispatch({ stage: 'CLASSIFY', page: 3, classifyResult: null, classifying: false })
        await setRobotState('DEMO_LOCKED'); active()

        // 3-2-1: fire each speak without blocking, 1 s between digits
        for (const n of [3, 2, 1]) {
          dispatch({ countdown: n })
          speak({ script: String(n) }).catch(() => {})
          await sleep(1000); active()
        }

        dispatch({ countdown: null, flash: true, classifying: true, caption: '📸 Snap!' })
        playShutter()
        const classifyResult = await classify(); active()
        dispatch({
          flash: false,
          classifying: false,
          classifyResult,
          page: 4,
          caption: `I think that's a ${prettyClass(classifyResult.className)}!`,
        })
        await sleep(2000); active()
        await motion(classifyResult.className).catch(() => {}); active()
        await sleep(1500); active()
        await motion('stand'); active()
        await setRobotState('IDLE'); active()

        // ── RECORD (page 5 → 6) ─────────────────────────────────────────────
        dispatch({ stage: 'RECORD', page: 5, recordStatus: 'idle', caption: '' })
        dispatch({ speaking: true })
        await speak({ script: 'RECORD' }); active()
        dispatch({ speaking: false })
        await sleep(3000); active()

        let gotAction = false
        while (!gotAction) {
          active()
          dispatch({ recording: true, recordStatus: 'recording', page: 6, caption: 'I\'m listening… 🎤' })
          const blob = await captureUtterance(); active()
          dispatch({ recording: false, recordStatus: 'thinking', caption: 'Hmm, let me think… 🤔' })
          const actionResult = await sendAudioForAction(blob); active()
          if (actionResult.hasAction) {
            gotAction = true
            dispatch({ recordStatus: 'action', caption: actionResult.content || 'Got it! Watch me try!' })
          } else {
            dispatch({
              recordStatus: 'clarify',
              caption: actionResult.content || 'I didn\'t quite catch that — tell me again!',
            })
            await sleep(1800); active()
          }
        }

        // Voice pipeline already moved the robot; hold then stand.
        await sleep(2000); active()
        await motion('stand').catch(() => {}); active()

        // ── NAME (page 6 → 7) ───────────────────────────────────────────────
        dispatch({ stage: 'NAME', page: 6, speaking: true, caption: 'What should we call this pose?' })
        await speak({ script: 'NAME' }); active()
        dispatch({ speaking: false, recording: true, recordStatus: 'recording', caption: 'Listening for a name… 🎤' })
        const nameBlob = await captureUtterance(); active()
        dispatch({ recording: false, recordStatus: 'thinking', caption: 'Got it!' })
        const transcript = await sendAudioForTranscript(nameBlob); active()
        const poseName = transcript.trim() || `Pose ${i + 1}`
        accumulatedNames.push(poseName)
        dispatch({
          poseName,
          poseNames: [...accumulatedNames],
          page: 7,
          recordStatus: 'idle',
          caption: '',
        })
        await sleep(2500); active()
      }

      // ── OUTRO (page 8) ───────────────────────────────────────────────────
      dispatch({
        stage: 'OUTRO',
        page: 8,
        speaking: true,
        poseNames: [...accumulatedNames],
        caption: 'How did Coral learn this?',
      })
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
