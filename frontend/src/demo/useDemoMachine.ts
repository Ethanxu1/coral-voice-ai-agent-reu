// Director demo state machine.
//
// Display state lives in a useReducer (serializable, drives the UI). The actual
// pipeline is an async runner that awaits each step in order and dispatches PATCH
// updates as it goes. No Redux / external store — just local state + refs.

import { useCallback, useEffect, useReducer, useRef } from 'react'
import {
  captureUtterance,
  mapFeatures,
  motion,
  move,
  playShutter,
  sendAudioForAction,
  sendAudioForTranscript,
  sendTextForAction,
  setRobotState,
  sleep,
  speak,
  watchForAction,
  type MapFeaturesResult,
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

export type InputMode = 'voice' | 'text'

/** A pose the child taught Coral: the name they gave it + the captured frame. */
export interface LearnedMove {
  name: string
  /** Base64 JPEG (no data: prefix) of the frame classified for this move. */
  frame: string | null
}

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
  classifyResult: MapFeaturesResult | null
  recording: boolean
  recordStatus: RecordStatus
  caption: string
  error: string | null
  /** Name the child gave this loop's pose (set on NAME stage). */
  poseName: string | null
  /** Every move taught so far: name + captured frame (for OUTRO/Page 8 display). */
  moves: LearnedMove[]
  /** 'voice' = mic capture; 'text' = typed entry. Toggled by the UI. */
  inputMode: InputMode
  /** True while the runner is blocked waiting for a typed submission (text mode). */
  awaitingText: boolean
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
  moves: [],
  inputMode: 'voice',
  awaitingText: false,
}

function reducer(state: DemoState, patch: Partial<DemoState>): DemoState {
  return { ...state, ...patch }
}

// Thrown internally to unwind the runner when the user exits/restarts.
const CANCELLED = Symbol('cancelled')

// How many times to re-snap when the pose can't be mapped (hips out of frame)
// before giving up and offering a retry/exit.
const MAX_RETAKES = 3

export function useDemoMachine() {
  const [state, dispatch] = useReducer(reducer, initialState)
  // Each run gets a token; if the active token changes mid-flight the runner aborts.
  const tokenRef = useRef(0)
  // Input mode is read live inside the async runner (toggled mid-flow), so mirror
  // it in a ref. textResolverRef holds the pending typed-input promise resolver.
  const inputModeRef = useRef<InputMode>('voice')
  const textResolverRef = useRef<((value: string) => void) | null>(null)

  useEffect(() => () => { tokenRef.current++ }, []) // abort on unmount

  // Block until the user submits typed text (text mode). Resolved by submitText,
  // or by exit() with '' to unwind a pending wait.
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

    dispatch({ ...initialState, inputMode: inputModeRef.current, stage: 'INTRO', page: 1, caption: 'Say hello to Coral!' })

    try {
      // ── INTRO (page 1) ──────────────────────────────────────────────────────
      dispatch({ speaking: true, caption: 'Coral is introducing herself…' })
      await speak({ script: 'INTRO' }); active()
      dispatch({ speaking: false, caption: 'Coral waves hello! 👋' })
      await motion('wave'); active()

      // ── LOOP: (page 2 coaching → CLASSIFY → RECORD → NAME) × N ─────────────
      const accumulatedMoves: LearnedMove[] = []

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

        // Countdown → snap → retarget. If the hips aren't in frame we can't map
        // the pose, so show a message and retake (up to MAX_RETAKES times).
        let classifyResult: MapFeaturesResult | null = null
        for (let take = 0; take < MAX_RETAKES; take++) {
          // 3-2-1: fire each speak without blocking, 1 s between digits
          for (const n of [3, 2, 1]) {
            dispatch({ countdown: n })
            speak({ script: String(n) }).catch(() => {})
            await sleep(1000); active()
          }

          dispatch({ countdown: null, flash: true, classifying: true, caption: '📸 Snap!' })
          playShutter()
          // Retarget the captured pose to servo commands (vision server) — no
          // MobileNetV3 class, just the child's real pose.
          const result = await mapFeatures(); active()
          if (result.poseDetected) {
            classifyResult = result
            break
          }
          // Hips not visible — surface the reason and loop back for another take.
          dispatch({
            flash: false,
            classifying: false,
            caption: result.detail || 'Make sure your wrists, shoulders, and hips are visible in the frame!',
          })
          await sleep(2500); active()
        }

        if (classifyResult === null) {
          dispatch({ stage: 'TIMEOUT', caption: 'I still can\'t see your whole body. Try again or exit?' })
          return
        }

        dispatch({
          flash: false,
          classifying: false,
          classifyResult,
          page: 4,
          caption: 'Now I\'ll copy your pose!',
        })
        await sleep(2000); active()
        await move(classifyResult.commands).catch(() => {}); active()
        await sleep(1500); active()
        // Hold the mimicked pose going into RECORD ("tell me how to fix it") —
        // no stand here. Unlock voice commands.
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
          let actionResult
          if (inputModeRef.current === 'text') {
            dispatch({ recording: false, recordStatus: 'idle', awaitingText: true, page: 6, caption: 'Type how Coral should fix the pose ⌨️' })
            const text = await awaitText(); active()
            dispatch({ awaitingText: false, recordStatus: 'thinking', caption: 'Hmm, let me think… 🤔' })
            actionResult = await sendTextForAction(text); active()
          } else {
            dispatch({ recording: true, recordStatus: 'recording', page: 6, caption: 'I\'m listening… 🎤' })
            const blob = await captureUtterance(); active()
            dispatch({ recording: false, recordStatus: 'thinking', caption: 'Hmm, let me think… 🤔' })
            actionResult = await sendAudioForAction(blob); active()
          }
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
        let transcript: string
        if (inputModeRef.current === 'text') {
          dispatch({ speaking: false, recording: false, recordStatus: 'idle', awaitingText: true, caption: 'Type a name for this pose ⌨️' })
          transcript = await awaitText(); active()
          dispatch({ awaitingText: false, recordStatus: 'thinking', caption: 'Got it!' })
        } else {
          dispatch({ speaking: false, recording: true, recordStatus: 'recording', caption: 'Listening for a name… 🎤' })
          const nameBlob = await captureUtterance(); active()
          dispatch({ recording: false, recordStatus: 'thinking', caption: 'Got it!' })
          transcript = await sendAudioForTranscript(nameBlob); active()
        }
        const poseName = transcript.trim() || `Pose ${i + 1}`
        accumulatedMoves.push({ name: poseName, frame: classifyResult.imageB64 })
        dispatch({
          poseName,
          moves: [...accumulatedMoves],
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
        moves: [...accumulatedMoves],
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
    textResolverRef.current?.('') // unblock a pending typed-input wait so the runner unwinds
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
