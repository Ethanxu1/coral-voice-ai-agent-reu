import { useCallback, useEffect, useRef, useState } from 'react'
import { sendAudioForTranscript } from '../api/actionSession'
import { designTurn, previewPose, type ChatTurn, type DesignChange } from '../api/poseDesign'
import { getJointPulses, setPose } from '../api/robot'
import { captureUtterance } from '../audio/capture'
import { killSpeech, speak } from '../audio/speech'
import { sleep } from '../utils/sleep'
import { armsOf } from './capture'

/** How long a glide into an accepted change takes. */
const APPLY_MS = 800
/** Messages of conversation sent with each request (the server takes up to 12), for "that's too much" to make sense. */
const HISTORY_MESSAGES = 12
/** After the mic fails (no permission, unplugged), wait this long before trying again. */
const MIC_RETRY_MS = 3000

/** 'off': the mic failed (no permission, unplugged); typing still works. */
export type MicState = 'listening' | 'thinking' | 'speaking' | 'off'

export interface Proposal {
  changes: DesignChange[]
  pulses: Record<string, number>
}

const isAbort = (e: unknown) => e instanceof DOMException && e.name === 'AbortError'

/**
 * The Pose Designer's voice conversation, while `active`: listen, ask the
 * server what the child wants, show a proposal as a ghost (`ghost`), and move
 * the robot only once the child accepts. Speaking and listening take turns, so
 * the mic never hears CORAL. CORAL starts by saying `intro`. `poseRef` holds
 * the pose being designed; it changes as proposals are accepted. `onDone` fires
 * when the child says they're finished.
 */
export function useDesignConversation(
  active: boolean,
  intro: string,
  poseRef: React.MutableRefObject<Record<string, number>>,
  onDone: () => void,
) {
  const [coral, setCoral] = useState('')
  const [heard, setHeard] = useState('')
  const [mic, setMic] = useState<MicState>('thinking')
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

  const say = async (text: string) => {
    setCoral(text)
    setMic('speaking')
    await speak({ text })
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

  /** One thing the child said (or typed), start to finish. */
  const handle = async (text: string) => {
    setHeard(text)
    setMic('thinking')
    const pending = Object.fromEntries((proposalRef.current?.changes ?? []).map((c) => [c.control, c.degrees]))
    const turn = await designTurn(text, poseRef.current, pending, historyRef.current).catch(() => null)
    if (!turn) {
      await say("I can't reach my brain right now. Is the server running?")
      return
    }
    remember('user', text)
    remember('assistant', turn.reply)
    if (turn.action === 'propose' && turn.proposedPulses) {
      setProposal({ changes: turn.changes, pulses: turn.proposedPulses })
      await say(turn.reply)
    } else if (turn.action === 'accept' && proposalRef.current) {
      const [, problem] = await Promise.all([say(turn.reply), applyProposal()])
      if (problem) await say(problem)
    } else if (turn.action === 'reject' && proposalRef.current) {
      setProposal(null)
      await say(turn.reply)
    } else if (turn.action === 'done') {
      setProposal(null)
      await say(turn.reply)
      onDoneRef.current()
    } else {
      await say(turn.reply)
    }
  }

  /** Listen until CORAL hears something (or text is typed), forever while this run lasts. */
  const listen = async (token: number) => {
    const alive = () => tokenRef.current === token
    await say(intro)
    while (alive()) {
      let text = typedRef.current
      typedRef.current = null
      if (text === null) {
        const abort = new AbortController()
        listenAbortRef.current = abort
        setMic('listening')
        try {
          const blob = await captureUtterance({ signal: abort.signal, onLevel: setLevel })
          setLevel(0)
          setMic('thinking')
          text = await sendAudioForTranscript(blob)
        } catch (e) {
          setLevel(0)
          if (!isAbort(e)) {
            console.warn('listening failed', e)
            setMic('off')
            await sleep(MIC_RETRY_MS)
          }
          continue
        }
      }
      if (!alive()) return
      if (text.trim()) await handle(text.trim())
    }
  }

  useEffect(() => {
    if (!active) return
    const token = ++tokenRef.current
    listen(token)
    return () => {
      tokenRef.current++
      listenAbortRef.current?.abort()
      killSpeech()
    }
  }, [active])

  /** Text typed instead of spoken: it takes the next turn, cutting CORAL off and stopping the mic. */
  const sendTyped = useCallback((text: string) => {
    typedRef.current = text
    killSpeech()
    listenAbortRef.current?.abort()
  }, [])

  return { coral, heard, mic, level, proposal, ghost, sendTyped }
}
