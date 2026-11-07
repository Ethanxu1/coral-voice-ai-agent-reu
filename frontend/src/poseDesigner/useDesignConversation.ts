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
/** Awake (after "hey CORAL", or after CORAL answers): go back to sleep if nobody starts talking within this. */
const AWAKE_MS = 8000

/**
 * 'asleep': waiting for "hey CORAL" (anything else is ignored); 'listening':
 * awake, the next thing said is for CORAL; 'off': the mic failed (no
 * permission, unplugged), typing still works.
 */
export type MicState = 'asleep' | 'listening' | 'thinking' | 'off'

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
 * followed by the request). Once awake, and for a follow-up after each answer,
 * the next utterance needs no wake word; after AWAKE_MS of silence it sleeps
 * again. Typed text always counts. `poseRef` holds the pose
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
   * while asleep). Returns whether CORAL is awake afterwards.
   */
  const handle = async (text: string, needsWakeWord: boolean): Promise<boolean> => {
    // Asleep, most of what's heard is background: don't flash "Thinking…" for it.
    if (!needsWakeWord) setMic('thinking')
    const pending = Object.fromEntries((proposalRef.current?.changes ?? []).map((c) => [c.control, c.degrees]))
    const turn = await designTurn(text, poseRef.current, pending, historyRef.current, needsWakeWord).catch(() => null)
    if (!turn) {
      setHeard(text)
      setCoral("I can't reach my brain right now. Is the server running?")
      return false
    }
    if (turn.action === 'ignore') return false
    setHeard(text)
    if (turn.action === 'wake') {
      playChime()
      return true
    }
    remember('user', text)
    remember('assistant', turn.reply)
    setCoral(turn.reply)
    if (turn.action === 'propose' && turn.proposedPulses) {
      setProposal({ changes: turn.changes, pulses: turn.proposedPulses })
    } else if (turn.action === 'accept' && proposalRef.current) {
      const problem = await applyProposal()
      if (problem) setCoral(problem)
    } else if (turn.action === 'reject' && proposalRef.current) {
      setProposal(null)
    } else if (turn.action === 'done') {
      setProposal(null)
      onDoneRef.current()
    }
    return true
  }

  /** One utterance (null if none: aborted, or `awake` and nobody spoke within AWAKE_MS). */
  const hear = async (awake: boolean): Promise<string | null> => {
    const abort = new AbortController()
    listenAbortRef.current = abort
    setMic(awake ? 'listening' : 'asleep')
    const doze = awake ? setTimeout(() => abort.abort(), AWAKE_MS) : undefined
    try {
      const blob = await captureUtterance({ signal: abort.signal, onLevel: setLevel, onSpeechStart: () => clearTimeout(doze) })
      setLevel(0)
      if (awake) setMic('thinking')
      return await sendAudioForTranscript(blob)
    } catch (e) {
      setLevel(0)
      if (!isAbort(e)) {
        console.warn('listening failed', e)
        setMic('off')
        await sleep(MIC_RETRY_MS)
      }
      return null
    } finally {
      clearTimeout(doze)
    }
  }

  /** Listen until CORAL hears something (or text is typed), forever while this run lasts. */
  const listen = async (token: number) => {
    const alive = () => tokenRef.current === token
    setCoral(intro)
    let awake = false
    while (alive()) {
      const typed = typedRef.current
      typedRef.current = null
      const text = typed ?? (await hear(awake))
      if (!alive()) return
      if (text === null) {
        // Typing aborts the mic and is picked up next time round; otherwise it timed out or failed.
        if (typedRef.current === null) awake = false
        continue
      }
      if (text.trim()) awake = await handle(text.trim(), typed === null && !awake)
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

  return { coral, heard, mic, level, proposal, ghost, sendTyped }
}
