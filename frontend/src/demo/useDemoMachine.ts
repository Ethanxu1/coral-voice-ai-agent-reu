// Director demo state machine.
//
// Display state lives in a useReducer (serializable, drives the UI). The actual
// pipeline is an async runner that awaits each step in order and dispatches PATCH
// updates as it goes. No Redux / external store — just local state + refs.

import { useCallback, useEffect, useReducer, useRef } from 'react'
import {
  captureUtterance,
  killSpeech,
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
  type ActionResult,
  type MapFeaturesResult,
} from './api'
import { LOOP_COUNT, RECORD_PROCESS_TIMEOUT_MS, WATCH_TIMEOUT_S } from './config'

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

// Sentinel returned by withTimeout when a step overruns its budget.
const TIMED_OUT = Symbol('timed-out')

/** Resolve to the promise's value, or TIMED_OUT if it takes longer than ms.
 *  The underlying promise is left to settle on its own (its socket closes on
 *  its own timeout); we just stop waiting for it. */
function withTimeout<T>(p: Promise<T>, ms: number): Promise<T | typeof TIMED_OUT> {
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(TIMED_OUT), ms)
    p.then(
      (v) => { clearTimeout(timer); resolve(v) },
      () => { clearTimeout(timer); resolve(TIMED_OUT) },
    )
  })
}

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

  // Abort on unmount, and silence Coral if the tab/page is closed mid-speech.
  useEffect(() => {
    const onHide = () => { killSpeech() }
    window.addEventListener('pagehide', onHide)
    return () => {
      window.removeEventListener('pagehide', onHide)
      tokenRef.current++
      killSpeech() // stop speech when leaving the demo (e.g. "← Back")
    }
  }, [])

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

    // Restart: silence any speech still playing from a previous run before the
    // new INTRO line, so they don't overlap (the speaker serializes utterances).
    await killSpeech()
    if (tokenRef.current !== token) return

    dispatch({ ...initialState, inputMode: inputModeRef.current, stage: 'INTRO', page: 1, caption: 'Say hello to Coral!' })

    try {
      // ── INTRO (page 1) ──────────────────────────────────────────────────────
      // Wave and the intro line play together — Coral greets while she talks.
      dispatch({ speaking: true, caption: 'Coral waves hello! 👋' })
      await Promise.all([
        speak({ script: 'INTRO' }),
        motion('wave').catch(() => {}),
      ]); active()
      dispatch({ speaking: false })

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
        await speak({ script: 'INSTRUCTIONS' }); active()
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
          // 3-2-1: show each digit for 1 s (no spoken countdown)
          for (const n of [3, 2, 1]) {
            dispatch({ countdown: n })
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
        // Ask for directions, then listen + interpret. If interpreting the
        // answer overruns RECORD_PROCESS_TIMEOUT_MS, abandon that attempt and
        // restart the ask (re-speak the RECORD prompt) rather than hang.
        dispatch({ stage: 'CORRECTIONS', page: 5, recordStatus: 'idle', caption: '' })

        let gotAction = false
        // If we advance to NAME before the motion finishes (timed out mid-
        // execution), this holds the still-running action promise so we can wait
        // for its real completion before standing, instead of cutting it off.
        let pendingAfterMoveOn: Promise<ActionResult> | null = null
        while (!gotAction) {
          active()
          // (Re)ask for directions.
          dispatch({ speaking: true, page: 5, recordStatus: 'idle' })
          await speak({ script: 'CORRECTIONS' }); active()
          dispatch({ speaking: false })

          let restart = false
          while (!gotAction && !restart) {
            active()
            let captured: string | Blob
            if (inputModeRef.current === 'text') {
              dispatch({ recording: false, recordStatus: 'idle', awaitingText: true, page: 6, caption: 'Type how Coral should fix the pose ⌨️' })
              captured = await awaitText(); active()
            } else {
              dispatch({ recording: true, recordStatus: 'recording', page: 6, caption: 'I\'m listening… 🎤' })
              captured = await captureUtterance(); active()
            }
            dispatch({ awaitingText: false, recording: false, recordStatus: 'thinking', caption: 'Hmm, let me think… 🤔' })

            // The server sends `action_started` right before it executes a motion.
            // If our wait times out but execution has already begun, move on to
            // NAME rather than re-asking (which would double up the movement).
            let actionStarted = false
            const onStarted = () => { actionStarted = true }
            const pending: Promise<ActionResult> =
              typeof captured === 'string'
                ? sendTextForAction(captured, 30000, onStarted)
                : sendAudioForAction(captured, 30000, onStarted)
            const actionResult = await withTimeout(pending, RECORD_PROCESS_TIMEOUT_MS); active()

            if (actionResult === TIMED_OUT) {
              if (actionStarted) {
                // Robot is already moving — proceed instead of re-asking, but
                // remember the promise so the stand waits for the motion to end.
                gotAction = true
                pendingAfterMoveOn = pending
                dispatch({ recordStatus: 'action', caption: 'Got it! Watch me try!' })
              } else {
                restart = true // break inner loop → re-ask for directions
                dispatch({ recordStatus: 'idle', caption: 'Hmm, that took a while — let me ask again 🔁' })
                await sleep(1200); active()
              }
            } else if (actionResult.hasAction) {
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
        }

        // Hold the mimicked/adjusted pose so the child sees it — do NOT stand
        // yet; the robot keeps the pose through naming and only stands once it's
        // been named. If we advanced before the motion finished, wait for its
        // real completion (the chat_response arrives only after execution) so the
        // held pose is the final one. Capped so a stuck request can't hang us.
        if (pendingAfterMoveOn) {
          dispatch({ caption: 'Watch me try! 🤖' })
          await withTimeout(pendingAfterMoveOn, 30000); active()
        } else {
          await sleep(2000); active()
        }

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
        // Pose has been named — now reset to stand for the next round.
        await motion('stand').catch(() => {}); active()
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
    killSpeech() // stop any in-progress line
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
