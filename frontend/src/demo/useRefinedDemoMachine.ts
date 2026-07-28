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
  startSubjectSelection,
  stopSubjectSelection,
  subscribeSubjectSelection,
  type ServoCommand,
  type SubjectSelectionState,
} from './api'
import { getRobotConfig } from './robotConfig'

export type RefinedStage =
  | 'IDLE'
  | 'SUBJECT_SELECT'
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
  audioUrl?: string
  // Intent classification metadata, populated after the user's message is classified.
  intentType?: string
  intentClassifier?: 'regex' | 'llm'
  intentReason?: string
}

export interface RefinedState {
  stage: RefinedStage
  messages: RefinedChatMsg[]
  countdown: number | null
  followActive: boolean
  capturedFrame: string | null
  micLevel: number
  orbState: 'listening' | 'thinking' | 'countdown' | 'muted'
  statusText: string
  savedPoses: string[]
  flash: boolean
  error: string | null
  pendingIntent: string | null
  muted: boolean
  // Index of the saved pose currently being performed on the end-session
  // replay screen, or null when not replaying.
  replayIdx: number | null
  // True while the backend collision + fall checks run on a captured pose —
  // drives the "Safety check…" badge over the sim panel.
  safetyChecking: boolean
  // Live vision-server subject-selection state, published every frame during
  // the SUBJECT_SELECT stage so the modal can show progress + status.
  selectionState: SubjectSelectionState
  selectionSubjectsCount: number
  selectionHoldProgress: number
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
  muted: false,
  replayIdx: null,
  safetyChecking: false,
  selectionState: 'idle',
  selectionSubjectsCount: 0,
  selectionHoldProgress: 0,
}

function reducer(s: RefinedState, p: Partial<RefinedState>): RefinedState {
  return { ...s, ...p }
}

const CANCELLED = Symbol('cancelled')

function agentMsg(text: string, chips?: string[]): RefinedChatMsg {
  return { role: 'agent', text, chips }
}
function childMsg(text: string, audioUrl?: string): RefinedChatMsg {
  return { role: 'child', text, audioUrl }
}

function updateLastChildMsgIntent(
  msgs: RefinedChatMsg[],
  intent: { type: string; classifier: 'regex' | 'llm'; reason: string }
): RefinedChatMsg[] {
  for (let i = msgs.length - 1; i >= 0; i--) {
    if (msgs[i].role === 'child') {
      const updated = [...msgs]
      updated[i] = {
        ...updated[i],
        intentType: intent.type,
        intentClassifier: intent.classifier,
        intentReason: intent.reason,
      }
      return updated
    }
  }
  return msgs
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
  // Object URLs for recorded user utterances; revoked on stop/unmount to avoid leaks.
  const audioUrlsRef = useRef<string[]>([])
  // Mute state is mirrored in a ref so the async capture loop can read it
  // without closing over a stale render value. The mic stays hot while muted;
  // muting only discards transcripts.
  const mutedRef = useRef(false)
  // When the user asks to re-capture during fine-tune, inject a synthetic
  // "capture my pose" turn so the main loop runs the full capture path again.
  const pendingCaptureRef = useRef(false)
  // Cleanup for the vision-server subject-selection WS subscription — held on
  // a ref so run() can tear it down early (cancel/stop) and unmount can
  // guarantee it's released.
  const selectionUnsubRef = useRef<(() => void) | null>(null)
  // Set while run() is blocked in the SUBJECT_SELECT stage; calling it
  // resolves the wait so the demo proceeds into LISTENING without a lock.
  const skipSelectionRef = useRef<(() => void) | null>(null)

  // Wrapped in a plain helper because TypeScript's control-flow narrowing
  // insists selectionUnsubRef.current is `null` at the finally/stop call sites
  // (it observes the `.current = null` inside the promise-resolve closure and
  // carries that narrowing out). Going through a function parameter forces
  // the type back to the ref's declared union.
  const releaseSelectionSubscription = useCallback(() => {
    const fn = selectionUnsubRef.current
    selectionUnsubRef.current = null
    if (typeof fn === 'function') fn()
  }, [])

  const revokeAudioUrls = useCallback(() => {
    audioUrlsRef.current.forEach((url) => {
      try {
        URL.revokeObjectURL(url)
      } catch {
        // ignore invalid urls
      }
    })
    audioUrlsRef.current = []
  }, [])

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
      revokeAudioUrls()
      releaseSelectionSubscription()
      stopSubjectSelection()
    }
  }, [abortCurrentCapture, revokeAudioUrls])

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

  const toggleMute = useCallback(() => {
    const next = !state.muted
    mutedRef.current = next

    // Update the UI immediately even if the main loop is currently blocked
    // waiting for audio or a transcription round-trip. Otherwise the orb/status
    // can lag behind the actual muted state by several seconds.
    const listeningStages: RefinedStage[] = ['LISTENING', 'FOLLOWING', 'LIBRARY', 'FINETUNE']
    if (listeningStages.includes(state.stage)) {
      const listeningStatus =
        state.stage === 'FINETUNE'
          ? 'Listening for tweaks…'
          : state.stage === 'LIBRARY'
          ? 'Pick a pose or say "make another"'
          : state.followActive
          ? 'Following your moves'
          : "I'm listening…"
      dispatch({
        muted: next,
        orbState: next ? 'muted' : 'listening',
        statusText: next ? 'Muted — mic is still on' : listeningStatus,
      })
    } else {
      dispatch({ muted: next })
    }
  }, [state.muted, state.stage, state.followActive])

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
    // Any previous selection subscription is dead now — drop it before this
    // run opens its own.
    selectionUnsubRef.current?.()
    selectionUnsubRef.current = null

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

    // ── Subject selection (raise-hand lock) ─────────────────────────────────
    // Start the session by locking on to one person so the rest of the demo
    // tracks only them, even when bystanders wander into frame.
    dispatch({
      ...INIT,
      stage: 'SUBJECT_SELECT',
      statusText: 'Raise your hand for 3 seconds to be selected',
      selectionState: 'selecting',
    })
    try {
      await startSubjectSelection()
    } catch {
      // If the vision server is unreachable we can't gate the session on it;
      // fall through and let the normal loop run without a locked subject.
    }
    active()

    await new Promise<void>((resolve, reject) => {
      const finish = () => {
        unsub()
        if (selectionUnsubRef.current === cleanup) selectionUnsubRef.current = null
        skipSelectionRef.current = null
        resolve()
      }
      const unsub = subscribeSubjectSelection((u) => {
        dispatch({
          selectionState: u.state,
          selectionSubjectsCount: u.subjectsCount,
          // Force 100% when selected — the backend resets hold_progress to 0
          // the moment state transitions out of "selecting", so the last frame
          // always carries 0 even though the hold completed.
          selectionHoldProgress: u.state === 'selected' ? 1 : u.holdProgress,
        })
        if (u.state === 'selected') finish()
      })
      const cleanup = () => {
        unsub()
        skipSelectionRef.current = null
        reject(CANCELLED)
      }
      selectionUnsubRef.current = cleanup
      skipSelectionRef.current = finish
    })
    active()

    dispatch({ ...INIT, stage: 'LISTENING', messages: msgs, statusText: "I'm listening…", selectionState: 'selected' })

    // Stable session ID shared by the intent classifier HTTP calls and the
    // persistent action websocket so Langfuse groups everything in one trace.
    const sessionId = `demo-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    const session = openActionSession(sessionId)

    const addMsg = (msg: RefinedChatMsg) => {
      msgs = [...msgs, msg]
      dispatch({ messages: msgs })
    }

    // Capture voice OR accept an injected chip/button text.
    // A per-call `settled` flag guards against late resolutions leaking into
    // a subsequent turn (e.g. captureUtterance's .then firing after a chip
    // click already resolved this promise).
    //
    // The microphone stays active even while muted so there is no startup delay
    // when the user unmutes. Muting only discards the transcript before it is
    // shown or acted on.
    const listenOrInject = async (): Promise<{ text: string; audioUrl?: string }> => {
      return new Promise<{ text: string; audioUrl?: string }>((resolve) => {
        const ctrl = new AbortController()
        let settled = false
        const settle = (val: string, audioUrl?: string) => {
          if (settled) return
          settled = true
          chipResolverRef.current = null
          if (captureAbortRef.current === ctrl) captureAbortRef.current = null
          resolve({ text: val, audioUrl })
        }

        captureAbortRef.current = ctrl
        chipResolverRef.current = (text: string) => settle(text)

        if (pendingCaptureRef.current) {
          pendingCaptureRef.current = false
          settle('capture my pose')
          return
        }

        captureUtterance({
          onLevel: (rms) => dispatch({ micLevel: rms }),
          signal: ctrl.signal,
        })
          .then((blob) => {
            if (settled) return
            const audioUrl = URL.createObjectURL(blob)
            audioUrlsRef.current.push(audioUrl)
            sendAudioForTranscript(blob)
              .then((t) => {
                if (settled) return
                if (mutedRef.current) {
                  // Muted: drop this utterance silently and keep the mic hot.
                  URL.revokeObjectURL(audioUrl)
                  const idx = audioUrlsRef.current.indexOf(audioUrl)
                  if (idx >= 0) audioUrlsRef.current.splice(idx, 1)
                  settle('')
                  return
                }
                settle(t, audioUrl)
              })
              .catch(() => settle('', audioUrl))
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
      const simOnly = getRobotConfig().simOnly
      let result
      try {
        [result] = await Promise.all([
          move(commands, simOnly),
          sleep(1500),
        ])
      } catch (error) {
        dispatch({ safetyChecking: false })
        const detail = error instanceof Error ? error.message : 'move failed'
        addMsg(agentMsg(
          simOnly
            ? `I couldn't move the simulation: ${detail}`
            : `I moved the simulation, but I couldn't reach the robot server: ${detail}`,
          ['Try again'],
        ))
        return false
      }
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
          orbState: mutedRef.current ? 'muted' : 'listening',
          statusText: mutedRef.current
            ? 'Muted — mic is still on'
            : followActive
            ? 'Following your moves'
            : "I'm listening…",
          micLevel: 0,
          capturedFrame: null,
          followActive,
        })

        const { text: transcript, audioUrl } = await listenOrInject()
        active()

        if (!transcript.trim()) {
          continue
        }

        // Show the child's transcript in the UI immediately — before the
        // classify-intent LLM roundtrip — so they get instant feedback that
        // they were heard. Otherwise there's a visible ~1–2s gap between
        // finishing a sentence and the text appearing.
        addMsg(childMsg(transcript, audioUrl))
        dispatch({ orbState: 'thinking', statusText: 'Thinking…', micLevel: 0 })
        const intentResult = await classifyIntent(transcript, followActive, msgs, sessionId)
        active()
        msgs = updateLastChildMsgIntent(msgs, intentResult)
        dispatch({ messages: msgs })

        // ── clarification: ask a follow-up, loop back ──
        if (intentResult.type === 'clarification') {
          addMsg(agentMsg(intentResult.question, ['Follow my movement', 'Capture my pose', 'My Poses']))
          continue
        }

        // ── conversation: chat/question — send to router, no approval modal ──
        if (intentResult.type === 'conversation') {
          dispatch({ orbState: 'thinking', statusText: 'Thinking…' })
          const chatResult = await session.sendText(intentResult.text, 'conversation')
          active()
          addMsg(agentMsg(chatResult.content || '', ['Follow my movement', 'Capture my pose', 'My Poses']))
          dispatch({ orbState: 'listening' })
          continue
        }

        // ── motion: show confirmation modal before executing ──
        if (intentResult.type === 'motion') {
          if (!intentResult.description?.trim()) {
            // No concrete movement proposed — fall back to chat instead of a redundant modal.
            dispatch({ orbState: 'thinking', statusText: 'Thinking…' })
            const chatResult = await session.sendText(transcript, 'conversation')
            active()
            addMsg(agentMsg(chatResult.content || '', ['Follow my movement', 'Capture my pose', 'My Poses']))
            dispatch({ orbState: mutedRef.current ? 'muted' : 'listening' })
            continue
          }
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
          const chatResult = await session.sendText(
            transcript,
            'motion',
            intentResult.description,
          )
          active()
          addMsg(agentMsg(chatResult.content || '', ['Follow my movement', 'Capture my pose', 'Save current pose']))
          dispatch({ orbState: mutedRef.current ? 'muted' : 'listening' })
          continue
        }

        // ── immediate: execute directly without confirmation ──
        const intent = intentResult.intent
        // ── follow_start ──
        if (intent === 'follow_start') {
          const result = await session.sendText(transcript, 'immediate')
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
          const result = await session.sendText(transcript, 'immediate')
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
          const { text: nameText, audioUrl: nameAudioUrl } = await listenOrInject()
          active()
          dispatch({ orbState: 'thinking', statusText: 'Got it!', micLevel: 0 })
          addMsg(childMsg(nameText, nameAudioUrl))
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

        // ── naming: launch the full save-and-name workflow ──
        if (intent === 'naming') {
          const suggestedName = (intentResult as { name?: string }).name?.trim()
          let poseName: string
          if (suggestedName) {
            poseName = suggestedName
            addMsg(sysMsg(`Saving as "${poseName}"!`))
          } else {
            addMsg(agentMsg("What would you like to name this pose?"))
            dispatch({ stage: 'NAMING', orbState: 'listening', statusText: 'Say a name…', micLevel: 0 })
            const { text: nameText, audioUrl: nameAudioUrl } = await listenOrInject()
            active()
            dispatch({ orbState: 'thinking', statusText: 'Got it!', micLevel: 0 })
            addMsg(childMsg(nameText, nameAudioUrl))
            poseName = nameText.trim() || `Pose ${Date.now()}`
          }
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
            dispatch({ orbState: mutedRef.current ? 'muted' : 'listening', statusText: mutedRef.current ? 'Muted — mic is still on' : 'Pick a pose or say "make another"', micLevel: 0 })
            const { text: lt, audioUrl: ltAudioUrl } = await listenOrInject()
            active()
            if (!lt.trim()) continue
            // Show the child transcript before classify-intent so the user
            // sees their words appear immediately.
            addMsg(childMsg(lt, ltAudioUrl))
            dispatch({ orbState: 'thinking', statusText: 'Thinking…', micLevel: 0 })
            const liResult = await classifyIntent(lt, false, msgs, sessionId)
            active()
            msgs = updateLastChildMsgIntent(msgs, liResult)
            dispatch({ messages: msgs })

            if (liResult.type === 'clarification') {
              addMsg(agentMsg(liResult.question, ['Make another', 'Follow my movement']))
              continue
            }

            if (liResult.type === 'motion') {
              if (!liResult.description?.trim()) {
                // No concrete movement proposed — chat instead of showing the modal.
                const lr = await session.sendText(lt, 'conversation')
                active()
                addMsg(agentMsg(lr.content || ''))
                dispatch({ stage: followActive ? 'FOLLOWING' : 'LISTENING', savedPoses })
                break
              }
              const libApproved = await awaitApproval(liResult.description)
              active()
              if (!libApproved) {
                addMsg(agentMsg("Got it — what would you like to do instead?", ['Make another', 'Follow my movement']))
                continue
              }
              const lr = await session.sendText(lt, 'motion', liResult.description)
              active()
              addMsg(agentMsg(lr.content || ''))
              dispatch({ stage: followActive ? 'FOLLOWING' : 'LISTENING', savedPoses })
              break
            }

            const li = liResult.type === 'immediate' ? liResult.intent : undefined
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
              dispatch({ stage: 'FINETUNE', capturedFrame: mapResult.imageB64, orbState: mutedRef.current ? 'muted' : 'listening', statusText: mutedRef.current ? 'Muted — mic is still on' : 'Listening for tweaks…' })
              let satisfied = false
              let followEscape = false
              let reCapture = false
              let suggestedName: string | null = null
              while (!satisfied) {
                active()
                dispatch({ orbState: mutedRef.current ? 'muted' : 'listening', statusText: mutedRef.current ? 'Muted — mic is still on' : 'Listening for tweaks…', micLevel: 0 })
                const { text: ft, audioUrl: ftAudioUrl } = await listenOrInject()
                active()
                if (!ft.trim()) continue
                addMsg(childMsg(ft, ftAudioUrl))
                const ftResult = await classifyIntent(ft, false, msgs, sessionId)
                active()
                msgs = updateLastChildMsgIntent(msgs, ftResult)
                dispatch({ messages: msgs })
                if (ftResult.type === 'clarification') {
                  addMsg(agentMsg(ftResult.question))
                  continue
                }
                if (ftResult.type === 'immediate' && ftResult.intent === 'follow_start') {
                  followEscape = true
                  break
                }
                if (ftResult.type === 'immediate' && ftResult.intent === 'capture') {
                  reCapture = true
                  break
                }
                if (ftResult.type === 'immediate' && (ftResult.intent === 'save_robot_pose' || ftResult.intent === 'naming')) {
                  if (ftResult.intent === 'naming' && ftResult.name?.trim()) {
                    suggestedName = ftResult.name.trim()
                  }
                  satisfied = true
                  break
                }
                if (ftResult.type === 'motion' && ftResult.description?.trim()) {
                  const ftApproved = await awaitApproval(ftResult.description)
                  active()
                  if (!ftApproved) {
                    addMsg(agentMsg("Got it — how should I tweak the pose instead?"))
                    continue
                  }
                  dispatch({ orbState: 'thinking', statusText: 'Applying…', micLevel: 0 })
                  const fr = await session.sendText(ft, 'motion', ftResult.description)
                  active()
                  addMsg(agentMsg(fr.content || ''))
                  if (fr.satisfied === true) satisfied = true
                } else {
                  dispatch({ orbState: 'thinking', statusText: 'Thinking…', micLevel: 0 })
                  const fr = await session.sendText(ft, 'conversation')
                  active()
                  addMsg(agentMsg(fr.content || ''))
                  if (fr.satisfied === true) satisfied = true
                }
              }
              if (followEscape) {
                const result = await session.sendText('follow my movement', 'immediate')
                active()
                addMsg(agentMsg(result.content || "I'm now following your movement!", ['Capture my pose', 'Stop following']))
                followActive = true
                dispatch({ followActive: true, capturedFrame: null })
                break  // exit library inner loop → main loop continues
              }
              if (reCapture) {
                addMsg(sysMsg("Let's try a new pose!"))
                pendingCaptureRef.current = true
                dispatch({ capturedFrame: null })
                break  // exit library inner loop; injected capture runs next
              }
              let poseName: string
              if (suggestedName) {
                poseName = suggestedName
                addMsg(sysMsg(`Saving as "${poseName}"!`))
              } else {
                dispatch({ stage: 'NAMING', orbState: 'listening', statusText: 'Say a name…', micLevel: 0 })
                const { text: nameText, audioUrl: nameAudioUrl } = await listenOrInject()
                active()
                dispatch({ orbState: 'thinking', statusText: 'Got it!', micLevel: 0 })
                addMsg(childMsg(nameText, nameAudioUrl))
                poseName = nameText.trim() || `Pose ${Date.now()}`
              }
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
            const lr = await session.sendText(
              lt,
              liResult.type === 'conversation' ? 'conversation' : 'immediate',
            )
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
            await session.sendText('stop following', 'immediate').catch(() => {})
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
          dispatch({ stage: 'FINETUNE', capturedFrame, orbState: mutedRef.current ? 'muted' : 'listening', statusText: mutedRef.current ? 'Muted — mic is still on' : 'Listening for tweaks…' })

          // FINETUNE loop
          let satisfied = false
          let followEscape = false
          let reCapture = false
          let suggestedName: string | null = null
          while (!satisfied) {
            active()
            dispatch({ orbState: mutedRef.current ? 'muted' : 'listening', statusText: mutedRef.current ? 'Muted — mic is still on' : 'Listening for tweaks…', micLevel: 0 })
            const { text: ft, audioUrl: ftAudioUrl } = await listenOrInject()
            active()
            if (!ft.trim()) continue
            addMsg(childMsg(ft, ftAudioUrl))
            const ftResult = await classifyIntent(ft, false, msgs, sessionId)
            active()
            msgs = updateLastChildMsgIntent(msgs, ftResult)
            dispatch({ messages: msgs })
            if (ftResult.type === 'clarification') {
              addMsg(agentMsg(ftResult.question))
              continue
            }
            if (ftResult.type === 'immediate' && ftResult.intent === 'follow_start') {
              followEscape = true
              break
            }
            if (ftResult.type === 'immediate' && ftResult.intent === 'capture') {
              reCapture = true
              break
            }
            if (ftResult.type === 'immediate' && (ftResult.intent === 'save_robot_pose' || ftResult.intent === 'naming')) {
              if (ftResult.intent === 'naming' && ftResult.name?.trim()) {
                suggestedName = ftResult.name.trim()
              }
              satisfied = true
              break
            }
            if (ftResult.type === 'motion' && ftResult.description?.trim()) {
              const ftApproved = await awaitApproval(ftResult.description)
              active()
              if (!ftApproved) {
                addMsg(agentMsg("Got it — how should I tweak the pose instead?"))
                continue
              }
              dispatch({ orbState: 'thinking', statusText: 'Applying…', micLevel: 0 })
              const fr = await session.sendText(ft, 'motion', ftResult.description)
              active()
              addMsg(agentMsg(fr.content || ''))
              if (fr.satisfied === true) satisfied = true
            } else {
              // Non-motion turns during fine-tune (conversation, remaining immediate)
              // skip the approval modal entirely.
              dispatch({ orbState: 'thinking', statusText: 'Thinking…', micLevel: 0 })
              const fr = await session.sendText(ft, 'conversation')
              active()
              addMsg(agentMsg(fr.content || ''))
              if (fr.satisfied === true) satisfied = true
            }
          }

          if (followEscape) {
            const result = await session.sendText('follow my movement', 'immediate')
            active()
            addMsg(agentMsg(result.content || "I'm now following your movement!", ['Capture my pose', 'Stop following']))
            followActive = true
            dispatch({ followActive: true, capturedFrame: null })
            continue
          }

          if (reCapture) {
            addMsg(sysMsg("Let's try a new pose!"))
            pendingCaptureRef.current = true
            dispatch({ capturedFrame: null })
            continue
          }

          // NAMING
          let poseName: string
          if (suggestedName) {
            poseName = suggestedName
            addMsg(sysMsg(`Saving as "${poseName}"!`))
          } else {
            dispatch({ stage: 'NAMING', orbState: 'listening', statusText: 'Say a name…', micLevel: 0 })
            const { text: nameText, audioUrl: nameAudioUrl } = await listenOrInject()
            active()
            dispatch({ orbState: 'thinking', statusText: 'Got it!', micLevel: 0 })
            addMsg(childMsg(nameText, nameAudioUrl))
            poseName = nameText.trim() || `Pose ${Date.now()}`
          }

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
      releaseSelectionSubscription()
      session.close()
    }
  }, [abortCurrentCapture, runExitReplay])

  const stop = useCallback(() => {
    tokenRef.current++
    chipResolverRef.current = null
    abortCurrentCapture()
    selectionUnsubRef.current?.()
    selectionUnsubRef.current = null
    revokeAudioUrls()
    setRobotState('IDLE')
    stopSubjectSelection()
    dispatch({ ...INIT })
  }, [abortCurrentCapture, revokeAudioUrls])

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

  // Skip the raise-hand lock and enter the listening loop without a locked
  // subject. Best-effort — resolves the pending wait if run() is blocked in
  // SUBJECT_SELECT; a no-op otherwise.
  const skipSubjectSelect = useCallback(() => {
    skipSelectionRef.current?.()
  }, [])

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
    toggleMute,
    skipSubjectSelect,
  }
}
