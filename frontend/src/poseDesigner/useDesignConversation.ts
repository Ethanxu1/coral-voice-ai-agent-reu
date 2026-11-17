import { useCallback, useEffect, useRef, useState } from 'react'
import { sendAudioForTranscript } from '../api/actionSession'
import { designTurn, previewPose, type ChatTurn, type DesignChange } from '../api/poseDesign'
import { getJointPulses, setPose } from '../api/robot'
import { captureUtterance } from '../audio/capture'
import { playChime } from '../audio/speech'
import { sleep } from '../utils/sleep'
import { armsOf } from './capture'

/** How long a glide into an accepted change takes. */
const APPLY_MS = 800
/** Messages of conversation sent with each request (the server takes up to 12), for "that's too much" to make sense. */
const HISTORY_MESSAGES = 12
/** After the mic fails (no permission, unplugged), wait this long before trying again. */
const MIC_RETRY_MS = 3000
/** After "hey CORAL": go back to sleep if nobody starts talking within this. */
const AWAKE_MS = 8000
/** After a proposal: this long to answer it ("yes", "no", "a bit higher") without the wake word. */
const FOLLOW_UP_MS = 6000

/**
 * 'asleep': waiting for "hey CORAL" (anything else is ignored); 'listening':
 * awake and the mic is open, the next thing said is for CORAL; 'off': the mic
 * failed (no permission, unplugged), typing still works.
 */
export type MicState = 'asleep' | 'listening' | 'thinking' | 'off'

/** How long the current listening window lasts (`ms` from when it opened; `id` changes with each window). */
export interface ListenWindow {
  id: number
  ms: number
}

export interface Proposal {
  changes: DesignChange[]
  pulses: Record<string, number>
}

const isAbort = (e: unknown) => e instanceof DOMException && e.name === 'AbortError'

/**
 * The Pose Designer's conversation, while `active`: listen, ask the server
 * what the child wants, show a proposal as a ghost (`ghost`), and move the
 * robot only once the child accepts. CORAL answers in text only (`coral`,
 * starting with `intro`), so the mic listens the whole time. It starts asleep:
 * speech counts only with "hey CORAL" (alone, which wakes it with a chime, or
 * followed by the request). Awake (AWAKE_MS after the wake word, FOLLOW_UP_MS
 * after a proposal) the next utterance needs no wake word. The window is a
 * deadline: noise that transcribes to nothing doesn't extend it, and any other
 * answer puts CORAL back to sleep. Typed text always counts. `poseRef` holds the pose
 * being designed; it changes as proposals are accepted. `onDone` fires when the
 * child says they're finished.
 */
export function useDesignConversation(
  active: boolean,
  intro: string,
  poseRef: React.MutableRefObject<Record<string, number>>,
  onDone: () => void,
) {
  const [coral, setCoral] = useState('')
  const [heard, setHeard] = useState('')
  const [mic, setMic] = useState<MicState>('asleep')
  const [level, setLevel] = useState(0)
  const [listenWindow, setListenWindow] = useState<ListenWindow | null>(null)
  const [speaking, setSpeaking] = useState(false)
  const [proposal, setProposalState] = useState<Proposal | null>(null)
  const [ghost, setGhost] = useState<Float32Array | null>(null)

  const proposalRef = useRef<Proposal | null>(null)
  const historyRef = useRef<ChatTurn[]>([])
  const typedRef = useRef<string | null>(null)
  const listenAbortRef = useRef<AbortController | null>(null)
  const tokenRef = useRef(0)
  const onDoneRef = useRef(onDone)
  onDoneRef.current = onDone

  const setProposal = (p: Proposal | null) => {
    proposalRef.current = p
    setProposalState(p)
    setGhost(null)
    if (p) previewPose(armsOf(p.pulses)).then((g) => proposalRef.current === p && setGhost(g)).catch(() => {})
  }

  const remember = (role: ChatTurn['role'], content: string) => {
    historyRef.current = [...historyRef.current, { role, content }].slice(-HISTORY_MESSAGES)
  }

  /** Move the robot into the waiting proposal; returns what to add if it didn't fully get there. */
  const applyProposal = async (): Promise<string | null> => {
    const p = proposalRef.current
    if (!p) return null
    setProposal(null)
    const result = await setPose(p.pulses, { durationMs: APPLY_MS, waitUntilArrived: true })
    if (result.status === 'blocked') return 'Whoa, that would tip me over, so I stayed put.'
    poseRef.current = { ...poseRef.current, ...armsOf(await getJointPulses()) }
    return result.safety.collisionClamped ? 'I went as far as I could without bumping into myself.' : null
  }

  /**
   * One thing the child said or typed, start to finish (`needsWakeWord`: said
   * while asleep). Returns how long to stay awake for a reply (0: back to sleep).
   */
  const handle = async (text: string, needsWakeWord: boolean): Promise<number> => {
    // Asleep, most of what's heard is background: don't flash "Thinking…" for it.
    if (!needsWakeWord) setMic('thinking')
    const pending = Object.fromEntries((proposalRef.current?.changes ?? []).map((c) => [c.control, c.degrees]))
    const turn = await designTurn(text, poseRef.current, pending, historyRef.current, needsWakeWord).catch(() => null)
    if (!turn) {
      setHeard(text)
      setCoral("I can't reach my brain right now. Is the server running?")
      return 0
    }
    if (turn.action === 'ignore') return 0
    setHeard(text)
    if (turn.action === 'wake') {
      playChime()
      return AWAKE_MS
    }
    remember('user', text)
    remember('assistant', turn.reply)
    setCoral(turn.reply)
    if (turn.action === 'propose' && turn.proposedPulses) {
      setProposal({ changes: turn.changes, pulses: turn.proposedPulses })
      return FOLLOW_UP_MS
    }
    if (turn.action === 'accept' && proposalRef.current) {
      const problem = await applyProposal()
      if (problem) setCoral(problem)
    } else if (turn.action === 'reject' && proposalRef.current) {
      setProposal(null)
    } else if (turn.action === 'done') {
      setProposal(null)
      onDoneRef.current()
    }
    return 0
  }

  /**
   * One utterance (null if none: aborted, or awake and nobody started talking
   * within `awakeMs`; null `awakeMs` = asleep). The state shows 'listening' only
   * once the mic is actually open.
   */
  const hear = async (awakeMs: number | null): Promise<string | null> => {
    const abort = new AbortController()
    listenAbortRef.current = abort
    let doze: ReturnType<typeof setTimeout> | undefined
    let open = false
    const onLevel = (rms: number) => {
      setLevel(rms)
      if (open) return
      open = true
      if (awakeMs === null) return setMic('asleep')
      setMic('listening')
      setListenWindow({ id: Date.now(), ms: awakeMs })
      doze = setTimeout(() => abort.abort(), awakeMs)
    }
    const onSpeechStart = () => {
      clearTimeout(doze)
      setSpeaking(true)
    }
    try {
      let blob: Blob
      try {
        blob = await captureUtterance({ signal: abort.signal, onLevel, onSpeechStart })
      } finally {
        clearTimeout(doze)
        setLevel(0)
        setSpeaking(false)
      }
      if (awakeMs !== null) setMic('thinking')
      return await sendAudioForTranscript(blob)
    } catch (e) {
      if (!isAbort(e)) {
        console.warn('listening failed', e)
        setMic('off')
        await sleep(MIC_RETRY_MS)
      }
      return null
    }
  }

  /** Listen until CORAL hears something (or text is typed), forever while this run lasts. */
  const listen = async (token: number) => {
    const alive = () => tokenRef.current === token
    setCoral(intro)
    /** When the current listening window ends (0: asleep). */
    let awakeUntil = 0
    while (alive()) {
      const typed = typedRef.current
      typedRef.current = null
      const awakeMs = awakeUntil - Date.now()
      const awake = awakeMs > 0
      const text = typed ?? (await hear(awake ? awakeMs : null))
      if (!alive()) return
      if (text === null) {
        // Typing aborts the mic and is picked up next time round; otherwise it timed out or failed.
        if (typedRef.current === null) awakeUntil = 0
        continue
      }
      // Noise heard as nothing: the window (if any) runs on, it isn't extended.
      if (!text.trim()) continue
      const stayAwakeMs = await handle(text.trim(), typed === null && !awake)
      awakeUntil = stayAwakeMs > 0 ? Date.now() + stayAwakeMs : 0
    }
  }

  useEffect(() => {
    if (!active) return
    const token = ++tokenRef.current
    listen(token)
    return () => {
      tokenRef.current++
      listenAbortRef.current?.abort()
    }
  }, [active])

  /** Text typed instead of spoken (no wake word needed): it takes the next turn, stopping the mic. */
  const sendTyped = useCallback((text: string) => {
    typedRef.current = text
    listenAbortRef.current?.abort()
  }, [])

  return { coral, heard, mic, level, listenWindow, speaking, proposal, ghost, sendTyped }
}
