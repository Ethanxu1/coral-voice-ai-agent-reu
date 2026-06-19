// Demo view — driven entirely by the Director over rosbridge.
//
// Subscribes to /demo_state (which phase we're in) and /demo/command (discrete
// UI actions like countdown / camera_click / record). On a `record` command it
// captures mic audio via the VAD, calls the AudioToAction service, and publishes
// the result back to the Director on /demo/audio_result.
//
// NOTE (skeleton): the visuals are intentionally minimal placeholders — countdown
// number, camera flash, classification text, suggestion chips. Polished animations
// are a TODO.
import { useEffect, useRef } from 'react'
import { useRosbridge } from '../ros/useRosbridge'
import { useAudioVAD } from '../utils/useAudioVAD'

const POSE_SUGGESTIONS = ['t-pose', 'dab', 'superhero', 'thinker', 'muscles', 'hand-raised', 'warrior2']

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve) => {
    const reader = new FileReader()
    reader.onloadend = () => resolve((reader.result as string).split(',')[1])
    reader.readAsDataURL(blob)
  })
}

export default function Demo() {
  const { connected, demoState, command, publishAudioResult, callAudioToAction } = useRosbridge()
  const recordingRef = useRef(false)

  const vad = useAudioVAD({
    onSpeechEnd: async (blob) => {
      if (!recordingRef.current) return
      const b64 = await blobToBase64(blob)
      try {
        const res = await callAudioToAction(b64)
        publishAudioResult(res)        // hand the result to the Director
      } catch {
        publishAudioResult({ has_action: false, verbal_response: '' })
      }
      recordingRef.current = false
      vad.pause()
    },
  })

  // React to discrete Director commands.
  useEffect(() => {
    if (!command) return
    if (command.action === 'record') {
      recordingRef.current = true
      vad.start().catch(() => { recordingRef.current = false })
    } else if (command.action === 'record_done') {
      recordingRef.current = false
      vad.pause()
    }
    // wave / await_gesture / camera_click / countdown are purely visual below
  }, [command])

  const state = demoState?.state ?? 'connecting'
  const move = demoState?.move as string | undefined
  const confidence = demoState?.confidence as number | undefined

  return (
    <div style={{ fontFamily: 'monospace', background: '#0e0e0e', color: '#ddd', minHeight: '100vh', padding: 24 }}>
      <header style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 24 }}>
        <h1 style={{ fontSize: 18, marginRight: 'auto' }}>CORAL — Robert</h1>
        <span style={{ color: connected ? '#a5d6a7' : '#e57373' }}>
          {connected ? 'rosbridge connected' : 'connecting…'}
        </span>
        <span style={{ background: '#1a237e', color: '#9fa8da', padding: '3px 10px', borderRadius: 3 }}>{state}</span>
      </header>

      {/* countdown */}
      {command?.action === 'countdown' && (
        <div style={{ fontSize: 96, textAlign: 'center' }}>{String(command.value)}</div>
      )}

      {/* camera flash placeholder */}
      {command?.action === 'camera_click' && (
        <div style={{ fontSize: 28, textAlign: 'center', color: '#fff' }}>📸 *click*</div>
      )}

      {/* intro: pose suggestions */}
      {state === 'intro' && (
        <div>
          <p>Strike your favorite pose! Some ideas:</p>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {POSE_SUGGESTIONS.map((p) => (
              <span key={p} style={{ background: '#141414', border: '1px solid #333', padding: '6px 12px', borderRadius: 4 }}>{p}</span>
            ))}
          </div>
          {command?.action === 'await_gesture' && <p style={{ color: '#9fa8da' }}>Cross your hands when ready…</p>}
        </div>
      )}

      {/* classification result */}
      {move && (
        <div style={{ marginTop: 16 }}>
          <p>I think you did a <strong style={{ color: '#a5d6a7' }}>{move}</strong>
            {confidence != null && <span style={{ color: '#666' }}> ({(confidence * 100).toFixed(0)}%)</span>}
          </p>
        </div>
      )}

      {/* record indicator */}
      {state === 'record' && (
        <div style={{ marginTop: 16, color: recordingRef.current ? '#e57373' : '#888' }}>
          {recordingRef.current ? '● recording — tell me how to fix my pose' : 'thinking…'}
        </div>
      )}

      {state === 'outro' && <p style={{ marginTop: 16 }}>Thanks for playing! 🎉</p>}
    </div>
  )
}
