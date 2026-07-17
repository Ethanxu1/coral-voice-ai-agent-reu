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
  playPose,
  playShutter,
  resetPose,
  saveCurrentPose,
  sendAudioForTranscript,
  setRobotState,
  sleep,
  type ServoCommand,
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
  pendingIntent: string | null
  // Index of the saved pose currently being performed on the end-session
  // replay screen, or null when not replaying.
  replayIdx: number | null
  // True while the backend collision + fall checks run on a captured pose —
  // drives the "Safety check…" badge over the sim panel.
  safetyChecking: boolean
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
  replayIdx: null,
  safetyChecking: false,
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
  const approvalResolverRef = useRef<((approved: boolean) => void) | null>(null)

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

  const injectText = useCallback((text: string) => {
    const resolve = chipResolverRef.current
    chipResolverRef.current = null
    abortCurrentCapture()
    resolve?.(text)
  }, [abortCurrentCapture])

  const approveIntent = useCallback(() => {
    const resolve = approvalResolverRef.current
    approvalResolverRef.current = null
    dispatch({ pendingIntent: null })
    resolve?.(true)
  }, [])

  const rejectIntent = useCallback(() => {
    const resolve = approvalResolverRef.current
    approvalResolverRef.current = null
    dispatch({ pendingIntent: null })
    resolve?.(false)
  }, [])

  // End-session replay: strike every saved pose in turn so the child sees each
  // move they taught. Highlight the move, play it on the robot, hold so it's
  // visible, reset to stand, then move on. Runs on its own cancellation token
  // (bumped by stop()/goToExit()/run()) so it halts the moment the user leaves
  // the exit screen.
  const runExitReplay = useCallback(async (names: string[]) => {
    abortCurrentCapture()
    const token = ++tokenRef.current
    const alive = () => tokenRef.current === token

    if (!names.length) {
      dispatch({ replayIdx: null })
      return
    }

    await setRobotState('IDLE')
    // Begin from a clean stand, then chain the moves directly (no reset between).
    await resetPose().catch(() => {})
    if (!alive()) return
    await sleep(700)

    for (let i = 0; i < names.length; i++) {
      if (!alive()) return
      dispatch({ replayIdx: i, statusText: `Performing "${names[i]}"` })
      try {
        // Transition straight from the current sim pose into the next move —
        // no reset to stand in between.
        await playPose(names[i], 1200)
      } catch {
        // A pose that fails to play (e.g. deleted) shouldn't stall the show.
      }
      if (!alive()) return
      await sleep(2400) // hold the pose so it's clearly visible
    }

    if (!alive()) return
    dispatch({ replayIdx: null, statusText: '' })
  }, [abortCurrentCapture])

  const run = useCallback(async () => {
    // Kill any capture left over from a prior run() invocation (strict-mode
    // double-mount, "Start Session" from ERROR/EXIT, etc.) before starting.
    abortCurrentCapture()

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

    const awaitApproval = (description: string): Promise<boolean> =>
      new Promise<boolean>((resolve) => {
        approvalResolverRef.current = resolve
        dispatch({ pendingIntent: description })
      })

    // Execute a captured pose's servo commands behind the backend safety
    // checks (kinematic collision clamp + dynamics fall check), holding a
    // visible "Safety check…" state for 1.5s while they run, then reporting
    // the verdict into the chat. If the fall check tripped, the server
    // executed 0% of the move — returns false so the caller can bail out of
    // the capture flow instead of pretending the pose landed.
    const moveWithSafetyCheck = async (commands: ServoCommand[]): Promise<boolean> => {
      dispatch({ safetyChecking: true, orbState: 'thinking', statusText: 'Running safety check…' })
      const [result] = await Promise.all([
        move(commands).catch(() => null),
        sleep(1500),
      ])
      dispatch({ safetyChecking: false })
      if (result && result.safety.fallBlocked) {
        addMsg(agentMsg(
          "Whoa — my safety check says that pose would tip me over, so I didn't do it! Let's try a different one.",
          ['Try again', 'Follow my movement'],
        ))
        return false
      }
      if (result && result.safety.collisionClamped) {
        addMsg(sysMsg(
          `Safety check: pulled the move back to ${Math.round(result.safety.safeFraction * 100)}% to avoid a collision.`,
        ))
      } else {
        addMsg(sysMsg('Safety check passed!'))
      }
      return true
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
        const intentResult = await classifyIntent(transcript, followActive, msgs)
        active()

        // ── clarification: ask a follow-up, loop back ──
        if (intentResult.type === 'clarification') {
          addMsg(agentMsg(intentResult.question, ['Follow my movement', 'Capture my pose', 'My Poses']))
          continue
        }

        // ── conversation: chat/question — send to router, no approval modal ──
        if (intentResult.type === 'conversation') {
          dispatch({ orbState: 'thinking', statusText: 'Thinking…' })
          const chatResult = await session.sendText(intentResult.text)
          active()
          addMsg(agentMsg(chatResult.content || '', ['Follow my movement', 'Capture my pose', 'My Poses']))
          dispatch({ orbState: 'listening' })
          continue
        }

        // ── motion: show confirmation modal before executing ──
        if (intentResult.type === 'motion') {
          const approved = await awaitApproval(intentResult.description)
          active()
          if (!approved) {
            addMsg(agentMsg(
              "Got it — what would you like to do instead?",
              ['Follow my movement', 'Capture my pose', 'My Poses'],
            ))
            continue
          }
          dispatch({ orbState: 'thinking', statusText: 'Applying…' })
          const chatResult = await session.sendText(intentResult.description)
          active()
          addMsg(agentMsg(chatResult.content || '', ['Follow my movement', 'Capture my pose', 'Save current pose']))
          dispatch({ orbState: 'listening' })
          continue
        }

        // ── immediate: execute directly without confirmation ──
        const intent = intentResult.intent
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

        // ── save_robot_pose: save current robot state directly (no camera) ──
        if (intent === 'save_robot_pose') {
          addMsg(agentMsg("What would you like to name this pose?"))
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
            `"${poseName}" is saved! Say a pose name to have me strike it, or let's keep going!`,
            ['My Poses', 'Follow my movement', 'Capture my pose'],
          ))
          dispatch({ savedPoses, stage: 'LISTENING', capturedFrame: null })
          continue
        }

        // ── exit ──
        if (intent === 'exit') {
          savedPoses = await listPoses()
          active()
          dispatch({ stage: 'EXIT_CONFIRM', savedPoses })
          runExitReplay(savedPoses)
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
            const liResult = await classifyIntent(lt, false, msgs)
            active()

            if (liResult.type === 'clarification') {
              addMsg(agentMsg(liResult.question, ['Make another', 'Follow my movement']))
              continue
            }

            if (liResult.type === 'motion') {
              const libApproved = await awaitApproval(liResult.description)
              active()
              if (!libApproved) {
                addMsg(agentMsg("Got it — what would you like to do instead?", ['Make another', 'Follow my movement']))
                continue
              }
              const lr = await session.sendText(liResult.description)
              active()
              addMsg(agentMsg(lr.content || ''))
              dispatch({ stage: followActive ? 'FOLLOWING' : 'LISTENING', savedPoses })
              break
            }

            const li = liResult.intent
            if (li === 'exit') {
              savedPoses = await listPoses()
              active()
              dispatch({ stage: 'EXIT_CONFIRM', savedPoses })
              runExitReplay(savedPoses)
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
              const moved = await moveWithSafetyCheck(mapResult.commands)
              active()
              if (!moved) {
                // Fall check blocked the move (0% executed) — back to the
                // library prompt instead of fine-tuning a pose that never landed.
                dispatch({ stage: 'LIBRARY', savedPoses, orbState: 'listening' })
                continue
              }
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
                addMsg(childMsg(ft))
                const ftResult = await classifyIntent(ft, false, msgs)
                active()
                if (ftResult.type === 'clarification') {
                  addMsg(agentMsg(ftResult.question))
                  continue
                }
                if (ftResult.type === 'immediate' && ftResult.intent === 'follow_start') {
                  followEscape = true
                  break
                }
                if (ftResult.type === 'immediate' && ftResult.intent === 'save_robot_pose') {
                  satisfied = true
                  break
                }
                const ftDesc = ftResult.type === 'motion' ? ftResult.description : ft
                const ftApproved = await awaitApproval(ftDesc)
                active()
                if (!ftApproved) {
                  addMsg(agentMsg("Got it — how should I tweak the pose instead?"))
                  continue
                }
                dispatch({ orbState: 'thinking', statusText: 'Applying…', micLevel: 0 })
                const fr = await session.sendText(ftDesc)
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

        // ── capture (also handles save_robot_pose while following as a safety net) ──
        if (intent === 'capture' || (intent === 'save_robot_pose' && followActive)) {
          let capturedFrame: string | null = null

          if (followActive) {
            // Robot already mirrors the user — freeze it in place, skip countdown/camera.
            await session.sendText('stop following').catch(() => {})
            followActive = false
            dispatch({ followActive: false })
            active()
            addMsg(sysMsg('Pose frozen!'))
          } else {
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

            const moved = await moveWithSafetyCheck(mapResult.commands)
            active()
            if (!moved) {
              // Fall check blocked the move (0% executed) — back to listening
              // instead of fine-tuning a pose that never landed.
              dispatch({ stage: currentStage, orbState: 'listening' })
              continue
            }
            capturedFrame = mapResult.imageB64
            addMsg(sysMsg('Pose captured!'))
          }

          addMsg(agentMsg('Awesome pose! Want to fine-tune it, or save it as is?', ['Fine-tune it', 'Save it']))
          dispatch({ stage: 'FINETUNE', capturedFrame, orbState: 'listening', statusText: 'Listening for tweaks…' })

          // FINETUNE loop
          let satisfied = false
          let followEscape = false
          while (!satisfied) {
            active()
            dispatch({ orbState: 'listening', statusText: 'Listening for tweaks…', micLevel: 0 })
            const ft = await listenOrInject()
            active()
            if (!ft.trim()) continue
            addMsg(childMsg(ft))
            const ftResult = await classifyIntent(ft, false, msgs)
            active()
            if (ftResult.type === 'clarification') {
              addMsg(agentMsg(ftResult.question))
              continue
            }
            if (ftResult.type === 'immediate' && ftResult.intent === 'follow_start') {
              followEscape = true
              break
            }
            if (ftResult.type === 'immediate' && ftResult.intent === 'save_robot_pose') {
              satisfied = true
              break
            }
            const ftDesc = ftResult.type === 'motion' ? ftResult.description : ft
            const ftApproved = await awaitApproval(ftDesc)
            active()
            if (!ftApproved) {
              addMsg(agentMsg("Got it — how should I tweak the pose instead?"))
              continue
            }
            dispatch({ orbState: 'thinking', statusText: 'Applying…', micLevel: 0 })
            const fr = await session.sendText(ftDesc)
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

      }
    } catch (err) {
      if (err === CANCELLED) return
      dispatch({ stage: 'ERROR', error: String(err) })
    } finally {
      chipResolverRef.current = null
      abortCurrentCapture()
      session.close()
    }
  }, [abortCurrentCapture, runExitReplay])

  const stop = useCallback(() => {
    tokenRef.current++
    chipResolverRef.current = null
    abortCurrentCapture()
    setRobotState('IDLE')
    dispatch({ ...INIT })
  }, [abortCurrentCapture])

  const goToLibrary = useCallback(async () => {
    tokenRef.current++
    chipResolverRef.current = null
    abortCurrentCapture()
    const names = await listPoses()
    dispatch({ stage: 'LIBRARY', savedPoses: names })
  }, [abortCurrentCapture])

  const goToExit = useCallback(async () => {
    tokenRef.current++
    chipResolverRef.current = null
    abortCurrentCapture()
    const names = await listPoses()
    dispatch({ stage: 'EXIT_CONFIRM', savedPoses: names, replayIdx: null })
    runExitReplay(names)
  }, [abortCurrentCapture, runExitReplay])

  const startAgain = useCallback(() => {
    run()
  }, [run])

  return {
    state,
    start: run,
    stop,
    injectText,
    approveIntent,
    rejectIntent,
    goToLibrary,
    goToExit,
    startAgain,
  }
}
