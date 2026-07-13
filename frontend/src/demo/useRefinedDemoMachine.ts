// State machine for the Refined Demo.
// Continuous voice loop: listen → classify intent → act → repeat until exit.

import { useCallback, useEffect, useReducer, useRef } from 'react'
import {
  captureUtterance,
  classifyIntent,
  killSpeech,
  listPoses,
  mapFeatures,
  move,
  openActionSession,
  playShutter,
  saveCurrentPose,
  sendAudioForTranscript,
  setRobotState,
  sleep,
} from './api'

export type RefinedStage =
  | 'IDLE'
  | 'LISTENING'
  | 'FOLLOWING'
  | 'COUNTDOWN'
  | 'CAPTURED'
  | 'FINETUNE'
  | 'NAMING'
  | 'LIBRARY'
  | 'EXIT_CONFIRM'
  | 'ERROR'

export interface RefinedChatMsg {
  role: 'agent' | 'child' | 'system'
  text: string
  chips?: string[]
}

export interface RefinedState {
  stage: RefinedStage
  messages: RefinedChatMsg[]
  countdown: number | null
  followActive: boolean
  capturedFrame: string | null
  micLevel: number
  orbState: 'listening' | 'thinking' | 'countdown'
  statusText: string
  savedPoses: string[]
  flash: boolean
  error: string | null
  // Non-null while the intent-approval modal is open. The classified intent
  // is shown to the user for approve/reject before we run the branch.
  pendingIntent: string | null
}

const INIT: RefinedState = {
  stage: 'IDLE',
  messages: [],
  countdown: null,
  followActive: false,
  capturedFrame: null,
  micLevel: 0,
  orbState: 'listening',
  statusText: "I'm listening…",
  savedPoses: [],
  flash: false,
  error: null,
  pendingIntent: null,
}

function reducer(s: RefinedState, p: Partial<RefinedState>): RefinedState {
  return { ...s, ...p }
}

const CANCELLED = Symbol('cancelled')

function agentMsg(text: string, chips?: string[]): RefinedChatMsg {
  return { role: 'agent', text, chips }
}
function childMsg(text: string): RefinedChatMsg {
  return { role: 'child', text }
}
function sysMsg(text: string): RefinedChatMsg {
  return { role: 'system', text }
}

export function useRefinedDemoMachine() {
  const [state, dispatch] = useReducer(reducer, INIT)
  const tokenRef = useRef(0)
  // Chip/button injection: when set, the next listenOrInject returns immediately
  const chipResolverRef = useRef<((text: string) => void) | null>(null)
  // Aborts the in-flight captureUtterance so the mic is released promptly on
  // chip clicks, restarts, and navigation. Without this, a stale getUserMedia
  // stream can block the next captureUtterance from acquiring the mic and the
  // orb sits in "listening" forever until reload.
  const captureAbortRef = useRef<AbortController | null>(null)
  // Resolves when the user approves/rejects the intent shown in the modal.
  // Any escape path (stop, goToLibrary, goToExit, run re-entry) must clear
  // this ref with `false` so the loop can reach its next active() check.
  const intentApprovalRef = useRef<((approved: boolean) => void) | null>(null)

  const abortCurrentCapture = useCallback(() => {
    const ctrl = captureAbortRef.current
    captureAbortRef.current = null
    ctrl?.abort()
  }, [])

  // Silence Coral if the tab/page is hidden mid-speech, and on unmount (e.g.
  // navigating away via "← Back"). Ported from the retired useDemoMachine.
  useEffect(() => {
    const onHide = () => { killSpeech() }
    window.addEventListener('pagehide', onHide)
    return () => {
      window.removeEventListener('pagehide', onHide)
      tokenRef.current++ // abort any in-flight run
      killSpeech()
      abortCurrentCapture()
    }
  }, [abortCurrentCapture])

  const clearPendingIntent = useCallback(() => {
    const resolve = intentApprovalRef.current
    intentApprovalRef.current = null
    resolve?.(false)
  }, [])

  const injectText = useCallback((text: string) => {
    const resolve = chipResolverRef.current
    chipResolverRef.current = null
    abortCurrentCapture()
    resolve?.(text)
  }, [abortCurrentCapture])

  const approveIntent = useCallback(() => {
    const resolve = intentApprovalRef.current
    intentApprovalRef.current = null
    dispatch({ pendingIntent: null })
    resolve?.(true)
  }, [])

  const rejectIntent = useCallback(() => {
    const resolve = intentApprovalRef.current
    intentApprovalRef.current = null
    dispatch({ pendingIntent: null })
    resolve?.(false)
  }, [])

  const run = useCallback(async () => {
    // Kill any capture left over from a prior run() invocation (strict-mode
    // double-mount, "Start Session" from ERROR/EXIT, etc.) before starting.
    abortCurrentCapture()
    clearPendingIntent()

    const token = ++tokenRef.current
    const active = () => {
      if (tokenRef.current !== token) throw CANCELLED
    }

    let msgs: RefinedChatMsg[] = [
      agentMsg(
        "Hi! I can follow your movements and help you capture poses. Just tell me what to do!",
        ['Follow my movement', 'Capture my pose', 'My Poses'],
      ),
    ]
    let followActive = false
    let savedPoses: string[] = []

    dispatch({ ...INIT, stage: 'LISTENING', messages: msgs, statusText: "I'm listening…" })

    const session = openActionSession()

    const addMsg = (msg: RefinedChatMsg) => {
      msgs = [...msgs, msg]
      dispatch({ messages: msgs })
    }

    // Show the classified intent to the user for approve/reject before
    // running the branch. If any escape path clears intentApprovalRef with
    // false (via clearPendingIntent), this resolves false too and the loop
    // reaches its next active() check to throw CANCELLED cleanly.
    const awaitApproval = async (intent: string): Promise<boolean> => {
      return new Promise<boolean>((resolve) => {
        intentApprovalRef.current = resolve
        dispatch({ pendingIntent: intent })
      })
    }

    // Capture voice OR accept an injected chip/button text.
    // A per-call `settled` flag guards against late resolutions leaking into
    // a subsequent turn (e.g. captureUtterance's .then firing after a chip
    // click already resolved this promise).
    const listenOrInject = async (): Promise<string> => {
      return new Promise<string>((resolve) => {
        const ctrl = new AbortController()
        let settled = false
        const settle = (val: string) => {
          if (settled) return
          settled = true
          chipResolverRef.current = null
          if (captureAbortRef.current === ctrl) captureAbortRef.current = null
          resolve(val)
        }

        captureAbortRef.current = ctrl
        chipResolverRef.current = settle

        captureUtterance({
          onLevel: (rms) => dispatch({ micLevel: rms }),
          signal: ctrl.signal,
        })
          .then((blob) => {
            if (settled) return
            sendAudioForTranscript(blob)
              .then((t) => settle(t))
              .catch(() => settle(''))
          })
          .catch(() => {
            // Always settle with empty on any error (including AbortError).
            // If a chip already settled, this is a no-op via the settled flag.
            // If the abort came from stop()/goToLibrary()/goToExit()/run() re-entry,
            // settling here unsticks this promise so the next active() check throws
            // CANCELLED and the loop exits cleanly — otherwise we'd hang forever.
            if (settled) return
            settle('')
          })
      })
    }

    try {
      while (true) {
        active()

        const currentStage = followActive ? 'FOLLOWING' : 'LISTENING'
        dispatch({
          stage: currentStage,
          orbState: 'listening',
          statusText: followActive ? 'Following your moves' : "I'm listening…",
          micLevel: 0,
          capturedFrame: null,
          followActive,
        })

        const transcript = await listenOrInject()
        active()

        if (!transcript.trim()) {
          continue
        }

        // Show the child's transcript in the UI immediately — before the
        // classify-intent LLM roundtrip — so they get instant feedback that
        // they were heard. Otherwise there's a visible ~1–2s gap between
        // finishing a sentence and the text appearing.
        addMsg(childMsg(transcript))
        dispatch({ orbState: 'thinking', statusText: 'Thinking…', micLevel: 0 })
        const intent = await classifyIntent(transcript, followActive)
        active()

        // Gate every intent behind explicit user approval (placeholder step —
        // final integration TBD). On reject, ask the user to rephrase and
        // return to listening.
        const approved = await awaitApproval(intent)
        active()
        if (!approved) {
          addMsg(agentMsg(
            "Got it — what would you like to do instead?",
            ['Follow my movement', 'Capture my pose', 'My Poses'],
          ))
          continue
        }

        // ── follow_start ──
        if (intent === 'follow_start') {
          const result = await session.sendText(transcript)
          active()
          addMsg(agentMsg(
            result.content || "I'm now following your movements!",
            ['Capture my pose', 'Stop following'],
          ))
          followActive = true
          dispatch({ followActive: true, capturedFrame: null })
          continue
        }

        // ── follow_stop ──
        if (intent === 'follow_stop') {
          const result = await session.sendText(transcript)
          active()
          addMsg(agentMsg(
            result.content || 'Stopped following.',
            ['Follow my movement', 'Capture my pose'],
          ))
          followActive = false
          dispatch({ followActive: false })
          continue
        }

        // ── exit ──
        if (intent === 'exit') {
          savedPoses = await listPoses()
          active()
          dispatch({ stage: 'EXIT_CONFIRM', savedPoses })
          return
        }

        // ── library ──
        if (intent === 'library') {
          savedPoses = await listPoses()
          active()
          addMsg(agentMsg(
            savedPoses.length
              ? `You have ${savedPoses.length} saved pose${savedPoses.length !== 1 ? 's' : ''}: ${savedPoses.join(', ')}. Say a pose name to strike it, or say "make another"!`
              : "You haven't saved any poses yet. Say \"capture my pose\" to get started!",
            savedPoses.length ? ['Make another', 'Follow my movement'] : ['Capture my pose', 'Follow my movement'],
          ))
          dispatch({ stage: 'LIBRARY', savedPoses })

          // Library inner loop
          while (true) {
            active()
            dispatch({ orbState: 'listening', statusText: 'Pick a pose or say "make another"', micLevel: 0 })
            const lt = await listenOrInject()
            active()
            if (!lt.trim()) continue
            // Show the child transcript before classify-intent so the user
            // sees their words appear immediately.
            addMsg(childMsg(lt))
            dispatch({ orbState: 'thinking', statusText: 'Thinking…', micLevel: 0 })
            const li = await classifyIntent(lt, false)
            active()
            const libApproved = await awaitApproval(li)
            active()
            if (!libApproved) {
              addMsg(agentMsg(
                "Got it — what would you like to do instead?",
                ['Make another', 'Follow my movement'],
              ))
              continue
            }
            if (li === 'exit') {
              savedPoses = await listPoses()
              active()
              dispatch({ stage: 'EXIT_CONFIRM', savedPoses })
              return
            }
            if (li === 'capture') {
              dispatch({ stage: 'LISTENING', savedPoses })
              // Process capture inline here instead of breaking out
              addMsg(sysMsg('Starting countdown…'))
              await setRobotState('DEMO_LOCKED')
              active()
              dispatch({ stage: 'COUNTDOWN', countdown: 3, orbState: 'countdown', statusText: 'Get ready…' })
              for (const n of [3, 2, 1]) {
                dispatch({ countdown: n })
                await sleep(1000)
                active()
              }
              dispatch({ countdown: null })
              dispatch({ stage: 'CAPTURED', flash: true, statusText: 'Got your pose!' })
              playShutter()
              const mapResult = await mapFeatures()
              active()
              await sleep(800)
              active()
              dispatch({ flash: false })
              await setRobotState('IDLE')
              active()
              if (!mapResult.poseDetected) {
                addMsg(agentMsg(
                  mapResult.detail || "I couldn't see your full body. Try stepping back!",
                  ['Try again', 'Follow my movement'],
                ))
                dispatch({ stage: 'LIBRARY', savedPoses })
                continue
              }
              await move(mapResult.commands).catch(() => {})
              active()
              addMsg(sysMsg('Pose captured!'))
              addMsg(agentMsg('Awesome pose! Want to fine-tune it, or save it as is?', ['Fine-tune it', 'Save it']))
              dispatch({ stage: 'FINETUNE', capturedFrame: mapResult.imageB64, orbState: 'listening', statusText: 'Listening for tweaks…' })
              let satisfied = false
              let followEscape = false
              while (!satisfied) {
                active()
                dispatch({ orbState: 'listening', statusText: 'Listening for tweaks…', micLevel: 0 })
                const ft = await listenOrInject()
                active()
                if (!ft.trim()) continue
                // Show child transcript immediately so the user sees their
                // words appear before the classify-intent + LLM roundtrip.
                addMsg(childMsg(ft))
                const ftIntent = await classifyIntent(ft, false)
                active()
                const ftApproved = await awaitApproval(ftIntent)
                active()
                if (!ftApproved) {
                  addMsg(agentMsg(
                    "Got it — how should I tweak the pose instead?",
                  ))
                  continue
                }
                if (ftIntent === 'follow_start') {
                  followEscape = true
                  break
                }
                dispatch({ orbState: 'thinking', statusText: 'Applying…', micLevel: 0 })
                const fr = await session.sendText(ft)
                active()
                addMsg(agentMsg(fr.content || ''))
                if (fr.satisfied === true) satisfied = true
              }
              if (followEscape) {
                const result = await session.sendText('follow my movement')
                active()
                addMsg(agentMsg(result.content || "I'm now following your movement!", ['Capture my pose', 'Stop following']))
                followActive = true
                dispatch({ followActive: true, capturedFrame: null })
                break  // exit library inner loop → main loop continues
              }
              dispatch({ stage: 'NAMING', orbState: 'listening', statusText: 'Say a name…', micLevel: 0 })
              const nameText = await listenOrInject()
              active()
              dispatch({ orbState: 'thinking', statusText: 'Got it!', micLevel: 0 })
              const poseName = nameText.trim() || `Pose ${Date.now()}`
              await saveCurrentPose(poseName)
              active()
              savedPoses = await listPoses()
              active()
              addMsg(sysMsg(`Saved as "${poseName}"!`))
              addMsg(agentMsg(
                `"${poseName}" is saved! Say a pose name to have me strike it, or let's make another!`,
                ['My Poses', 'Make another'],
              ))
              dispatch({ savedPoses, stage: 'LIBRARY', capturedFrame: null })
              followActive = false
              // Stay in library loop
              continue
            }
            // General command from library view (childMsg already added above)
            const lr = await session.sendText(lt)
            active()
            addMsg(agentMsg(lr.content || ''))
            if (li !== 'library') {
              dispatch({ stage: followActive ? 'FOLLOWING' : 'LISTENING', savedPoses })
              break
            }
          }
          continue
        }

        // ── capture ──
        if (intent === 'capture') {
          if (followActive) {
            await session.sendText('stop following').catch(() => {})
            followActive = false
            dispatch({ followActive: false })
          }
          active()

          addMsg(sysMsg('Starting countdown…'))

          await setRobotState('DEMO_LOCKED')
          active()

          dispatch({ stage: 'COUNTDOWN', countdown: 3, orbState: 'countdown', statusText: 'Get ready…' })
          for (const n of [3, 2, 1]) {
            dispatch({ countdown: n })
            await sleep(1000)
            active()
          }
          dispatch({ countdown: null })

          dispatch({ stage: 'CAPTURED', flash: true, statusText: 'Got your pose!' })
          playShutter()
          const mapResult = await mapFeatures()
          active()
          await sleep(800)
          active()
          dispatch({ flash: false })

          await setRobotState('IDLE')
          active()

          if (!mapResult.poseDetected) {
            addMsg(agentMsg(
              mapResult.detail || "I couldn't see your full body. Try stepping back!",
              ['Try again', 'Follow my movement'],
            ))
            dispatch({ stage: currentStage })
            continue
          }

          await move(mapResult.commands).catch(() => {})
          active()

          addMsg(sysMsg('Pose captured!'))
          addMsg(agentMsg('Awesome pose! Want to fine-tune it, or save it as is?', ['Fine-tune it', 'Save it']))
          dispatch({ stage: 'FINETUNE', capturedFrame: mapResult.imageB64, orbState: 'listening', statusText: 'Listening for tweaks…' })

          // FINETUNE loop
          let satisfied = false
          let followEscape = false
          while (!satisfied) {
            active()
            dispatch({ orbState: 'listening', statusText: 'Listening for tweaks…', micLevel: 0 })
            const ft = await listenOrInject()
            active()
            if (!ft.trim()) continue
            // Show child transcript immediately so the user sees their words
            // appear before the classify-intent + LLM roundtrip.
            addMsg(childMsg(ft))
            const ftIntent = await classifyIntent(ft, false)
            active()
            const ftApproved = await awaitApproval(ftIntent)
            active()
            if (!ftApproved) {
              addMsg(agentMsg(
                "Got it — how should I tweak the pose instead?",
              ))
              continue
            }
            if (ftIntent === 'follow_start') {
              followEscape = true
              break
            }
            dispatch({ orbState: 'thinking', statusText: 'Applying…', micLevel: 0 })
            const fr = await session.sendText(ft)
            active()
            addMsg(agentMsg(fr.content || ''))
            if (fr.satisfied === true) satisfied = true
          }

          if (followEscape) {
            const result = await session.sendText('follow my movement')
            active()
            addMsg(agentMsg(result.content || "I'm now following your movement!", ['Capture my pose', 'Stop following']))
            followActive = true
            dispatch({ followActive: true, capturedFrame: null })
            continue
          }

          // NAMING
          dispatch({ stage: 'NAMING', orbState: 'listening', statusText: 'Say a name…', micLevel: 0 })
          const nameText = await listenOrInject()
          active()
          dispatch({ orbState: 'thinking', statusText: 'Got it!', micLevel: 0 })
          const poseName = nameText.trim() || `Pose ${Date.now()}`

          await saveCurrentPose(poseName)
          active()
          savedPoses = await listPoses()
          active()

          addMsg(sysMsg(`Saved as "${poseName}"!`))
          addMsg(agentMsg(
            `"${poseName}" is saved! Say a pose name to have me strike it, or let's make another!`,
            ['My Poses', 'Make another'],
          ))
          dispatch({ savedPoses, stage: 'LISTENING', capturedFrame: null })
          followActive = false
          continue
        }

        // ── chat (general motion/conversation) ──
        dispatch({ orbState: 'thinking', statusText: 'Thinking…' })
        const chatResult = await session.sendText(transcript)
        active()
        addMsg(agentMsg(chatResult.content || '', ['Follow my movement', 'Capture my pose']))
        dispatch({ orbState: 'listening' })
      }
    } catch (err) {
      if (err === CANCELLED) return
      dispatch({ stage: 'ERROR', error: String(err) })
    } finally {
      chipResolverRef.current = null
      abortCurrentCapture()
      clearPendingIntent()
      session.close()
    }
  }, [abortCurrentCapture, clearPendingIntent])

  const stop = useCallback(() => {
    tokenRef.current++
    chipResolverRef.current = null
    abortCurrentCapture()
    clearPendingIntent()
    setRobotState('IDLE')
    dispatch({ ...INIT })
  }, [abortCurrentCapture, clearPendingIntent])

  const goToLibrary = useCallback(async () => {
    tokenRef.current++
    chipResolverRef.current = null
    abortCurrentCapture()
    clearPendingIntent()
    const names = await listPoses()
    dispatch({ stage: 'LIBRARY', savedPoses: names })
  }, [abortCurrentCapture, clearPendingIntent])

  const goToExit = useCallback(() => {
    tokenRef.current++
    chipResolverRef.current = null
    abortCurrentCapture()
    clearPendingIntent()
    setRobotState('IDLE')
    dispatch({ stage: 'EXIT_CONFIRM' })
  }, [abortCurrentCapture, clearPendingIntent])

  const startAgain = useCallback(() => {
    run()
  }, [run])

  return {
    state,
    start: run,
    stop,
    injectText,
    goToLibrary,
    goToExit,
    startAgain,
    approveIntent,
    rejectIntent,
  }
}
