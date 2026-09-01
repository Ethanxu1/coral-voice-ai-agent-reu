// State machine for the Refined Demo.
// Continuous voice loop: listen → classify intent → act → repeat until exit.

import { useCallback, useEffect, useReducer, useRef } from 'react'
import { beginHardwareDispatch } from './hardwareDispatchStatus'
import {
  captureUtterance,
  classifyIntent,
  extractName,
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
  type ActionResult,
  type MoveSafety,
  type ServoCommand,
  type SubjectSelectionState,
} from './api'


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
  // When true, the robot's spoken responses are silenced (text still shows).
  audioMuted: boolean
  // When false, intent approval pop-ups are skipped and every classified
  // intent is auto-approved. Useful for demos where the modal interrupts flow.
  approvalsEnabled: boolean
  // Index of the saved pose currently being performed on the end-session
  // replay screen, or null when not replaying.
  replayIdx: number | null
  // The child-reorderable move sequence for the end-session dance, seeded
  // from savedPoses on entering EXIT_CONFIRM. savedPoses itself stays in its
  // original (alphabetical) order for the "you saved N poses" count text.
  danceOrder: string[]
  // True while the dance loop is actively cycling through danceOrder.
  isDancePlaying: boolean
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
  audioMuted: false,
  approvalsEnabled: false,
  replayIdx: null,
  danceOrder: [],
  isDancePlaying: false,
  safetyChecking: false,
  selectionState: 'idle',
  selectionSubjectsCount: 0,
  selectionHoldProgress: 0,
}

function reducer(s: RefinedState, p: Partial<RefinedState>): RefinedState {
  return { ...s, ...p }
}

const CANCELLED = Symbol('cancelled')

// Dance pacing: real servo travel time (hardware-relevant) for each move,
// kept close to the 1.0s safety reference StabilityChecker's ramp_seconds
// assumes (see backend memory), plus a much shorter pure-UX pause between
// moves so the sequence reads as a continuous dance rather than stop-and-go.
const DANCE_POSE_MS = 750
const DANCE_PAUSE_MS = 280

// Shared yes/no matchers, used for both the intent-approval modal and the
// pose-naming confirmation loop. Mirrors backend/app/services/intent.py's
// _YES_RE/_NO_RE — keep in sync.
const YES_RE = /\b(yes|yeah|yep|yup|sure|ok|okay|go ahead|do it)\b/i
const NO_RE = /\b(no|nope|nah|cancel|never mind|nevermind|stop)\b/i

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
  // Aborts the in-flight voice-approval capture when the user clicks Approve/Reject.
  const voiceApprovalAbortRef = useRef<AbortController | null>(null)
  // Mirrors state.approvalsEnabled so the async run() loop reads the current
  // setting rather than the value captured when the run started.
  const approvalsEnabledRef = useRef(false)
  // Object URLs for recorded user utterances; revoked on stop/unmount to avoid leaks.
  const audioUrlsRef = useRef<string[]>([])
  // Mute state is mirrored in a ref so the async capture loop can read it
  // without closing over a stale render value. The mic stays hot while muted;
  // muting only discards transcripts.
  const mutedRef = useRef(false)
  // Output mute ref so async audio callbacks can check it without stale closure.
  const audioMutedRef = useRef(false)
  // Currently playing assistant audio element; stopped on new turns or stop().
  const currentAudioRef = useRef<HTMLAudioElement | null>(null)
  // Object URLs for assistant TTS audio; revoked on stop/unmount.
  const assistantAudioUrlsRef = useRef<string[]>([])
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
  // Mirrors state.danceOrder so the async dance loop always reads the latest
  // reorder without a stale closure — a reorder made while paused takes
  // effect the next time startDance() is called.
  const danceOrderRef = useRef<string[]>([])
  // Cancellation token for the end-session dance loop, separate from the main
  // run() loop's tokenRef: pausing the dance must not look like the whole
  // session was cancelled, and resuming it must not touch unrelated in-flight
  // work guarded by tokenRef.
  const danceTokenRef = useRef(0)

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

  const stopCurrentAudio = useCallback(() => {
    const audio = currentAudioRef.current
    if (audio) {
      audio.pause()
      audio.src = ''
      currentAudioRef.current = null
    }
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
    assistantAudioUrlsRef.current.forEach((url) => {
      try {
        URL.revokeObjectURL(url)
      } catch {
        // ignore invalid urls
      }
    })
    assistantAudioUrlsRef.current = []
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
      danceTokenRef.current++ // stop any in-flight end-session dance loop
      killSpeech()
      stopCurrentAudio()
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
    voiceApprovalAbortRef.current?.abort()
    voiceApprovalAbortRef.current = null
    dispatch({ pendingIntent: null })
    resolve?.(true)
  }, [])

  const rejectIntent = useCallback(() => {
    const resolve = approvalResolverRef.current
    approvalResolverRef.current = null
    voiceApprovalAbortRef.current?.abort()
    voiceApprovalAbortRef.current = null
    dispatch({ pendingIntent: null })
    resolve?.(false)
  }, [])

  // Turn the intent approval pop-ups on/off. Switching them off while a modal
  // is already up auto-approves that pending intent so the loop isn't left
  // blocked on a resolver no one can reach anymore.
  const toggleApprovals = useCallback(() => {
    const next = !approvalsEnabledRef.current
    approvalsEnabledRef.current = next
    if (!next) {
      const resolve = approvalResolverRef.current
      approvalResolverRef.current = null
      voiceApprovalAbortRef.current?.abort()
      voiceApprovalAbortRef.current = null
      dispatch({ approvalsEnabled: next, pendingIntent: null })
      resolve?.(true)
    } else {
      dispatch({ approvalsEnabled: next })
    }
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

  const toggleAudioMute = useCallback(() => {
    const next = !state.audioMuted
    audioMutedRef.current = next
    if (next) {
      stopCurrentAudio()
    }
    dispatch({ audioMuted: next })
  }, [state.audioMuted, stopCurrentAudio])

  // End-session dance: loops the child's saved moves continuously (like a
  // dance routine) until paused. pauseDance() lets the in-flight move finish,
  // then stops scheduling further ones — the robot freezes wherever it is,
  // no reset to stand, so the frozen pose stays visible while reordering.
  // startDance() begins a fresh, independently-cancellable loop that re-reads
  // danceOrderRef at the top of every lap, so a reorder made while paused
  // takes effect the next time it's called.
  const pauseDance = useCallback(() => {
    danceTokenRef.current++
    dispatch({ isDancePlaying: false })
  }, [])

  const startDance = useCallback(async () => {
    const token = ++danceTokenRef.current
    const alive = () => danceTokenRef.current === token
    dispatch({ isDancePlaying: true })

    while (alive()) {
      const names = danceOrderRef.current
      if (!names.length) {
        dispatch({ isDancePlaying: false, replayIdx: null })
        return
      }
      // One dispatch "in flight" for the whole lap, not per-pose — playPose()
      // itself only covers the network round-trip, but the pose is still
      // visibly holding through the sleep below, so a per-call wrap would
      // flicker the "Executing on robot…" pill off between poses.
      const endDispatch = beginHardwareDispatch()
      try {
        for (let i = 0; i < names.length; i++) {
          if (!alive()) return
          dispatch({ replayIdx: i, statusText: `Performing "${names[i]}"` })
          try {
            // Transition straight from the current pose into the next move —
            // no reset to stand in between, so the dance flows continuously.
            await playPose(names[i], DANCE_POSE_MS)
          } catch {
            // A pose that fails to play (e.g. deleted) shouldn't stall the show.
          }
          if (!alive()) return
          await sleep(DANCE_PAUSE_MS)
        }
      } finally {
        endDispatch()
      }
      // Loop back to the top and keep dancing until paused.
    }
  }, [])

  const run = useCallback(async () => {
    // Kill any capture left over from a prior run() invocation (strict-mode
    // double-mount, "Start Session" from ERROR/EXIT, etc.) before starting.
    abortCurrentCapture()
    // Stop any dance loop left over from a prior session's exit screen.
    danceTokenRef.current++
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

    const handleAssistantAudio = (audioUrl: string) => {
      assistantAudioUrlsRef.current.push(audioUrl)
      for (let i = msgs.length - 1; i >= 0; i--) {
        if (msgs[i].role === 'agent') {
          msgs = [...msgs]
          msgs[i] = { ...msgs[i], audioUrl }
          dispatch({ messages: msgs })
          break
        }
      }
      if (!audioMutedRef.current) {
        stopCurrentAudio()
        const audio = new Audio(audioUrl)
        currentAudioRef.current = audio
        audio.play().catch(() => {
          // Browser autoplay policy may block; user can click the replay button.
        })
        audio.onended = () => {
          if (currentAudioRef.current === audio) {
            currentAudioRef.current = null
          }
        }
      }
    }

    // Thin wrapper so every backend turn auto-plays its TTS audio.
    // Failures return a child-friendly fallback instead of crashing the loop.
    const sendText = async (
      text: string,
      intentType?: 'motion' | 'conversation' | 'immediate' | 'clarification',
      description?: string,
      timeoutMs = 30000,
    ): Promise<ActionResult> => {
      try {
        return await session.sendText(text, intentType, description, timeoutMs, handleAssistantAudio)
      } catch (err) {
        const detail = err instanceof Error ? err.message : 'connection hiccup'
        return {
          transcript: text,
          content: `Oops, I lost connection for a second (${detail}). Can you try again?`,
          hasAction: false,
          satisfied: null,
          safety: null,
        }
      }
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

    // Capture a short yes/no answer while the approval modal is visible.
    // Returns true/false or null when the utterance isn't clearly yes/no.
    const listenForYesNo = async (signal: AbortSignal): Promise<boolean | null> => {
      try {
        const blob = await captureUtterance({
          silenceMs: 900,
          maxMs: 7000,
          signal,
        })
        const text = (await sendAudioForTranscript(blob)).trim().toLowerCase()
        if (!text) return null
        if (YES_RE.test(text)) return true
        if (NO_RE.test(text)) return false
        return null
      } catch {
        return null
      }
    }

    const awaitApproval = (description: string): Promise<boolean> => {
      // Pop-ups toggled off: auto-approve without ever showing the modal.
      if (!approvalsEnabledRef.current) return Promise.resolve(true)
      return new Promise<boolean>((resolve) => {
        let resolved = false
        const doResolve = (val: boolean) => {
          if (resolved) return
          resolved = true
          approvalResolverRef.current = null
          voiceApprovalAbortRef.current?.abort()
          voiceApprovalAbortRef.current = null
          dispatch({ pendingIntent: null })
          resolve(val)
        }

        approvalResolverRef.current = doResolve
        dispatch({ pendingIntent: description })

        // Also accept a spoken yes/no. The mic is free because the main run()
        // loop is blocked on this promise. Loop a few times so a mumbled or
        // unclear first answer doesn't force the child to use the buttons.
        const voiceLoop = async () => {
          for (let attempt = 0; attempt < 3 && !resolved; attempt++) {
            const ctrl = new AbortController()
            voiceApprovalAbortRef.current = ctrl
            const answer = await listenForYesNo(ctrl.signal)
            if (resolved) return
            if (answer === true) {
              doResolve(true)
              return
            }
            if (answer === false) {
              doResolve(false)
              return
            }
            // Unrecognized answer: keep the modal up and listen once more,
            // unless this was the last attempt.
          }
        }
        voiceLoop()
      })
    }

    // Report a fine-tuning adjustment's safety verdict into the chat. The
    // adjustment moves run server-side through the motion planner (not our own
    // /move call), so the checks that ran there come back on the chat response
    // — without this the child sees a clamped or blocked tweak silently do
    // nothing, while a captured pose explains itself. `null` means the turn
    // executed no motion (pure conversation), so there's nothing to report.
    const reportMotionSafety = (safety: MoveSafety | null | undefined): void => {
      if (!safety) return
      if (safety.fallBlocked) {
        addMsg(sysMsg("Safety check: that tweak would tip me over, so I stayed put."))
      } else if (safety.collisionClamped) {
        addMsg(sysMsg(
          `Safety check: pulled the move back to ${Math.round(safety.safeFraction * 100)}% to avoid a collision.`,
        ))
      } else {
        addMsg(sysMsg('Safety check passed!'))
      }
    }

    // Execute a captured pose's servo commands behind the backend safety
    // checks (kinematic collision clamp + dynamics fall check), holding a
    // visible "Safety check…" state for 1.5s while they run, then reporting
    // the verdict into the chat. If the fall check tripped, the server
    // executed 0% of the move — returns false so the caller can bail out of
    // the capture flow instead of pretending the pose landed.
    const moveWithSafetyCheck = async (commands: ServoCommand[]): Promise<boolean> => {
      dispatch({ safetyChecking: true, orbState: 'thinking', statusText: 'Running safety check…' })
      let result
      try {
        [result] = await Promise.all([
          move(commands),
          sleep(1500),
        ])
      } catch (error) {
        dispatch({ safetyChecking: false })
        const detail = error instanceof Error ? error.message : 'move failed'
        addMsg(agentMsg(
          `I couldn't move: ${detail}`,
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

    // Resolve a confirmed, filtered pose name: ask (unless a name was already
    // suggested by the classifier), filter the raw answer through the backend
    // LLM extractor (strips filler like "let's name it X" -> "X"), then loop
    // asking for confirmation until the child says yes — a bare "no" prompts
    // a fresh answer, anything else is treated as the corrected name.
    const resolveConfirmedPoseName = async (suggestedName?: string): Promise<string> => {
      let candidate: string
      if (suggestedName?.trim()) {
        candidate = suggestedName.trim()
      } else {
        addMsg(agentMsg("What would you like to name this pose?"))
        dispatch({ stage: 'NAMING', orbState: 'listening', statusText: 'Say a name or type it below…', micLevel: 0 })
        const { text: nameText, audioUrl } = await listenOrInject()
        active()
        dispatch({ orbState: 'thinking', statusText: 'Got it!', micLevel: 0 })
        addMsg(childMsg(nameText, audioUrl))
        candidate = nameText.trim() || `Pose ${Date.now()}`
      }

      while (true) {
        let filtered: string
        try {
          filtered = (await extractName(candidate)).trim() || candidate
        } catch {
          filtered = candidate
        }
        active()

        addMsg(agentMsg(`Should I call it "${filtered}"? Say yes, or tell me the right name.`))
        dispatch({ stage: 'NAMING', orbState: 'listening', statusText: 'Say yes, or say/type the correct name…', micLevel: 0 })
        const { text: replyText, audioUrl: replyAudioUrl } = await listenOrInject()
        active()
        dispatch({ orbState: 'thinking', statusText: 'Got it!', micLevel: 0 })

        const reply = replyText.trim()
        if (!reply) return filtered // silence/timeout: don't stall the demo
        addMsg(childMsg(reply, replyAudioUrl))

        if (YES_RE.test(reply)) return filtered

        const strippedOfNo = reply.replace(new RegExp(NO_RE.source, 'gi'), '').trim()
        if (NO_RE.test(reply) && strippedOfNo.length === 0) {
          addMsg(agentMsg("Okay, what should I call it instead?"))
          dispatch({ stage: 'NAMING', orbState: 'listening', statusText: 'Say a name or type it below…', micLevel: 0 })
          const { text: retryText, audioUrl: retryAudioUrl } = await listenOrInject()
          active()
          dispatch({ orbState: 'thinking', statusText: 'Got it!', micLevel: 0 })
          addMsg(childMsg(retryText, retryAudioUrl))
          candidate = retryText.trim() || filtered
          continue
        }

        // Anything else ("no, call it X", or the corrected name directly)
        // becomes the next candidate.
        candidate = reply
      }
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
          const chatResult = await sendText(intentResult.text, 'conversation')
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
            const chatResult = await sendText(transcript, 'conversation')
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
          const chatResult = await sendText(
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
          const result = await sendText(transcript, 'immediate')
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
          const result = await sendText(transcript, 'immediate')
          active()
          addMsg(agentMsg(
            result.content || 'Stopped following.',
            ['Follow my movement', 'Capture my pose'],
          ))
          followActive = false
          dispatch({ followActive: false })
          continue
        }

        // ── play_pose: strike a saved pose — the backend resolves the spoken
        // name against the saved-pose library and executes it ──
        if (intent === 'play_pose') {
          const result = await sendText(transcript, 'immediate')
          active()
          addMsg(agentMsg(
            result.content || 'Done!',
            ['My Poses', 'Follow my movement', 'Capture my pose'],
          ))
          dispatch({ orbState: mutedRef.current ? 'muted' : 'listening' })
          continue
        }

        // ── save_robot_pose: save current robot state directly (no camera) ──
        if (intent === 'save_robot_pose') {
          const poseName = await resolveConfirmedPoseName()
          active()
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
          const poseName = await resolveConfirmedPoseName(suggestedName)
          active()
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
          danceOrderRef.current = savedPoses
          dispatch({ stage: 'EXIT_CONFIRM', savedPoses, danceOrder: savedPoses, replayIdx: null })
          await setRobotState('IDLE')
          await resetPose().catch(() => {})
          active()
          await sleep(700)
          startDance()
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
                const lr = await sendText(lt, 'conversation')
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
              const lr = await sendText(lt, 'motion', liResult.description)
              active()
              addMsg(agentMsg(lr.content || ''))
              dispatch({ stage: followActive ? 'FOLLOWING' : 'LISTENING', savedPoses })
              break
            }

            const li = liResult.type === 'immediate' ? liResult.intent : undefined
            if (li === 'exit') {
              savedPoses = await listPoses()
              active()
              danceOrderRef.current = savedPoses
              dispatch({ stage: 'EXIT_CONFIRM', savedPoses, danceOrder: savedPoses, replayIdx: null })
              await setRobotState('IDLE')
              await resetPose().catch(() => {})
              active()
              await sleep(700)
              startDance()
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
                dispatch({ capturedFrame: null })
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
                  const fr = await sendText(ft, 'motion', ftResult.description)
                  active()
                  reportMotionSafety(fr.safety)
                  addMsg(agentMsg(fr.content || ''))
                  if (fr.satisfied === true) satisfied = true
                } else {
                  dispatch({ orbState: 'thinking', statusText: 'Thinking…', micLevel: 0 })
                  const fr = await sendText(ft, 'conversation')
                  active()
                  addMsg(agentMsg(fr.content || ''))
                  if (fr.satisfied === true) satisfied = true
                }
              }
              if (followEscape) {
                const result = await sendText('follow my movement', 'immediate')
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
              const poseName = await resolveConfirmedPoseName(suggestedName ?? undefined)
              active()
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
            const lr = await sendText(
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
            await sendText('stop following', 'immediate').catch(() => {})
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
            dispatch({ capturedFrame: null })
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
              const fr = await sendText(ft, 'motion', ftResult.description)
              active()
              reportMotionSafety(fr.safety)
              addMsg(agentMsg(fr.content || ''))
              if (fr.satisfied === true) satisfied = true
            } else {
              // Non-motion turns during fine-tune (conversation, remaining immediate)
              // skip the approval modal entirely.
              dispatch({ orbState: 'thinking', statusText: 'Thinking…', micLevel: 0 })
              const fr = await sendText(ft, 'conversation')
              active()
              addMsg(agentMsg(fr.content || ''))
              if (fr.satisfied === true) satisfied = true
            }
          }

          if (followEscape) {
            const result = await sendText('follow my movement', 'immediate')
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
          const poseName = await resolveConfirmedPoseName(suggestedName ?? undefined)
          active()

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
  }, [abortCurrentCapture, startDance])

  const stop = useCallback(() => {
    tokenRef.current++
    danceTokenRef.current++
    chipResolverRef.current = null
    abortCurrentCapture()
    voiceApprovalAbortRef.current?.abort()
    voiceApprovalAbortRef.current = null
    stopCurrentAudio()
    selectionUnsubRef.current?.()
    selectionUnsubRef.current = null
    revokeAudioUrls()
    setRobotState('IDLE')
    stopSubjectSelection()
    dispatch({ ...INIT })
  }, [abortCurrentCapture, stopCurrentAudio, revokeAudioUrls])

  const goToLibrary = useCallback(async () => {
    tokenRef.current++
    chipResolverRef.current = null
    abortCurrentCapture()
    voiceApprovalAbortRef.current?.abort()
    voiceApprovalAbortRef.current = null
    const names = await listPoses()
    dispatch({ stage: 'LIBRARY', savedPoses: names })
  }, [abortCurrentCapture])

  const goToExit = useCallback(async () => {
    tokenRef.current++
    chipResolverRef.current = null
    abortCurrentCapture()
    voiceApprovalAbortRef.current?.abort()
    voiceApprovalAbortRef.current = null
    const names = await listPoses()
    danceOrderRef.current = names
    dispatch({ stage: 'EXIT_CONFIRM', savedPoses: names, danceOrder: names, replayIdx: null })
    await setRobotState('IDLE')
    await resetPose().catch(() => {})
    await sleep(700)
    startDance()
  }, [abortCurrentCapture, startDance])

  const reorderDance = useCallback((fromIndex: number, toIndex: number) => {
    const next = [...danceOrderRef.current]
    const [moved] = next.splice(fromIndex, 1)
    if (moved === undefined) return
    next.splice(toIndex, 0, moved)
    danceOrderRef.current = next
    dispatch({ danceOrder: next })
  }, [])

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
    toggleApprovals,
    goToLibrary,
    goToExit,
    startAgain,
    toggleMute,
    toggleAudioMute,
    skipSubjectSelect,
    startDance,
    pauseDance,
    reorderDance,
  }
}
