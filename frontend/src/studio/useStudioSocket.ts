import { useEffect, useReducer, useRef } from 'react'

import type { StudioEvent, StudioSocketState } from './types'

const STUDIO_WS = import.meta.env.VITE_STUDIO_WS ?? 'ws://localhost:8000/studio/ws'
const INITIAL_RECONNECT_MS = 500
const MAX_RECONNECT_MS = 5_000

const initialState: StudioSocketState = {
  connected: false,
  latestEvent: null,
  recognition: {},
  holds: {},
  executingSequenceId: null,
  statusMessage: null,
}

type Action =
  | { type: 'connected'; value: boolean }
  | { type: 'event'; event: StudioEvent }

export function studioSocketReducer(state: StudioSocketState, action: Action): StudioSocketState {
  if (action.type === 'connected') return { ...state, connected: action.value }
  const event = action.event
  if (event.type === 'recognition') {
    return {
      ...state,
      latestEvent: event,
      recognition: {
        ...state.recognition,
        [event.subjectId]: {
          label: event.label,
          confidence: event.confidence,
          reason: event.reason,
        },
      },
    }
  }
  if (event.type === 'hold_progress') {
    return {
      ...state,
      latestEvent: event,
      holds: { ...state.holds, [event.subjectId]: event.progress },
    }
  }
  if (event.type === 'execution_started') {
    return { ...state, latestEvent: event, executingSequenceId: event.sequenceId, statusMessage: null }
  }
  return {
    ...state,
    latestEvent: event,
    executingSequenceId: null,
    statusMessage: event.message ?? null,
  }
}

function parseEvent(data: string): StudioEvent | 'ping' | null {
  try {
    const raw = JSON.parse(data) as Record<string, unknown>
    if (raw.type === 'ping') return 'ping'
    const common = { type: raw.type as StudioEvent['type'] }
    if (raw.type === 'recognition') {
      return {
        ...common,
        type: 'recognition',
        subjectId: String(raw.subject_id),
        label: raw.label == null ? null : String(raw.label),
        confidence: Number(raw.confidence),
        reason: raw.reason == null ? undefined : String(raw.reason),
      }
    }
    if (raw.type === 'hold_progress') {
      return {
        ...common,
        type: 'hold_progress',
        subjectId: String(raw.subject_id),
        label: raw.label == null ? undefined : String(raw.label),
        progress: Number(raw.progress),
      }
    }
    if (raw.type === 'execution_started' || raw.type === 'execution_completed') {
      return {
        ...common,
        type: raw.type,
        sequenceId: String(raw.sequence_id),
        message: raw.message == null ? undefined : String(raw.message),
      }
    }
    if (raw.type === 'execution_blocked') {
      return {
        type: 'execution_blocked',
        sequenceId: String(raw.sequence_id),
        failedStep: raw.failed_step == null ? undefined : Number(raw.failed_step),
        message: String(raw.message ?? 'Execution blocked'),
      }
    }
    if (raw.type === 'hardware_unavailable') {
      return {
        type: 'hardware_unavailable',
        sequenceId: String(raw.sequence_id),
        message: String(raw.message ?? 'Hardware unavailable'),
      }
    }
  } catch {
    return null
  }
  return null
}

export function useStudioSocket(url = STUDIO_WS): StudioSocketState {
  const [state, dispatch] = useReducer(studioSocketReducer, initialState)
  const socketRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    let stopped = false
    let reconnectAttempt = 0
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null

    const connect = () => {
      if (stopped) return
      const socket = new WebSocket(url)
      socketRef.current = socket
      socket.onopen = () => {
        reconnectAttempt = 0
        dispatch({ type: 'connected', value: true })
      }
      socket.onmessage = (message) => {
        const event = parseEvent(String(message.data))
        if (event === 'ping') {
          socket.send(JSON.stringify({ type: 'pong' }))
        } else if (event) {
          dispatch({ type: 'event', event })
        }
      }
      socket.onclose = () => {
        dispatch({ type: 'connected', value: false })
        if (stopped) return
        const delay = Math.min(INITIAL_RECONNECT_MS * 2 ** reconnectAttempt, MAX_RECONNECT_MS)
        reconnectAttempt += 1
        reconnectTimer = setTimeout(connect, delay)
      }
    }

    connect()
    return () => {
      stopped = true
      if (reconnectTimer) clearTimeout(reconnectTimer)
      socketRef.current?.close()
      socketRef.current = null
    }
  }, [url])

  return state
}
