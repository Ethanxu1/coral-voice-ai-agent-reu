// State machine for the Refined Demo.
// Continuous voice loop: listen → classify intent → act → repeat until exit.

import { useCallback, useReducer, useRef } from 'react'
import {
  captureUtterance,
  classifyIntent,
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

  const injectText = useCallback((text: string) => {
    const resolve = chipResolverRef.current
    chipResolverRef.current = null
    resolve?.(text)
  }, [])

  const run = useCallback(async () => {
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

    // Capture voice OR accept an injected chip/button text
    const listenOrInject = async (): Promise<string> => {
      return new Promise<string>((resolve) => {
        chipResolverRef.current = resolve
        captureUtterance({ onLevel: (rms) => dispatch({ micLevel: rms }) })
          .then((blob) => {
            // Only resolve if we haven't been resolved by a chip already
            if (chipResolverRef.current !== null) {
              chipResolverRef.current = null
              sendAudioForTranscript(blob).then(resolve).catch(() => resolve(''))
            }
          })
          .catch(() => {
            if (chipResolverRef.current !== null) {
              chipResolverRef.current = null
              resolve('')
            }
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

        dispatch({ orbState: 'thinking', statusText: 'Thinking…', micLevel: 0 })
        const intent = await classifyIntent(transcript, followActive)
        active()

        // ── follow_start ──
        if (intent === 'follow_start') {
          addMsg(childMsg(transcript))
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
          addMsg(childMsg(transcript))
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
          addMsg(childMsg(transcript))
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
            dispatch({ orbState: 'thinking', statusText: 'Thinking…', micLevel: 0 })
            const li = await classifyIntent(lt, false)
            active()
            if (li === 'exit') {
              savedPoses = await listPoses()
              active()
              dispatch({ stage: 'EXIT_CONFIRM', savedPoses })
              return
            }
            if (li === 'capture') {
              dispatch({ stage: 'LISTENING', savedPoses })
              addMsg(childMsg(lt))
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
                const ftIntent = await classifyIntent(ft, false)
                active()
                if (ftIntent === 'follow_start') {
                  addMsg(childMsg(ft))
                  followEscape = true
                  break
                }
                addMsg(childMsg(ft))
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
            // General command from library view
            addMsg(childMsg(lt))
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

          addMsg(childMsg(transcript))
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
            const ftIntent = await classifyIntent(ft, false)
            active()
            if (ftIntent === 'follow_start') {
              addMsg(childMsg(ft))
              followEscape = true
              break
            }
            addMsg(childMsg(ft))
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
        addMsg(childMsg(transcript))
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
      session.close()
    }
  }, [])

  const stop = useCallback(() => {
    tokenRef.current++
    chipResolverRef.current = null
    setRobotState('IDLE')
    dispatch({ ...INIT })
  }, [])

  const goToLibrary = useCallback(async () => {
    tokenRef.current++
    chipResolverRef.current = null
    const names = await listPoses()
    dispatch({ stage: 'LIBRARY', savedPoses: names })
  }, [])

  const goToExit = useCallback(() => {
    tokenRef.current++
    chipResolverRef.current = null
    setRobotState('IDLE')
    dispatch({ stage: 'EXIT_CONFIRM' })
  }, [])

  const startAgain = useCallback(() => {
    run()
  }, [run])

  return { state, start: run, stop, injectText, goToLibrary, goToExit, startAgain }
}
