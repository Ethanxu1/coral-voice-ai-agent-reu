import type { PageProps } from './TestUIRouter'
import { TextEntry } from './TextEntry'

const BAR_COUNT = 14
const DELAYS = [0, 0.18, 0.36, 0.08, 0.55, 0.28, 0.70, 0.12, 0.44, 0.62, 0.22, 0.50, 0.34, 0.76]
const DURATIONS = [0.8, 1.1, 0.7, 1.3, 0.9, 1.0, 0.75, 1.2, 0.85, 1.05, 0.95, 0.65, 1.15, 0.9]

function statusLabel(status: string, recording: boolean, caption: string): string {
  if (caption) return caption
  if (recording || status === 'recording') return 'Listening…'
  if (status === 'thinking') return 'Thinking… 🤔'
  if (status === 'action') return 'Got it! ✅'
  if (status === 'clarify') return "Hmm, tell me again 🔁"
  return 'Listening…'
}

export default function Page6_RecordMic({ state, submitText }: PageProps) {
  // Text mode: a text box instead of the microphone visual.
  if (state.inputMode === 'text') {
    return (
      <div className="tui-page p6-layout">
        {state.recordStatus === 'thinking' ? (
          <div className="p6-label">Thinking… 🤔</div>
        ) : (
          <TextEntry
            prompt={state.caption || 'Type how Coral should fix the pose'}
            placeholder="e.g. move your right arm a little lower"
            onSubmit={submitText}
          />
        )}
      </div>
    )
  }

  const live = state.recording || state.recordStatus === 'recording'
  return (
    <div className="tui-page p6-layout">
      {/* pulsing ring + mic */}
      <div className="p6-mic-wrap" style={{ opacity: live ? 1 : 0.6 }}>
        <div className="p6-ring" />
        <div className="p6-ring" />
        <div className="p6-ring" />
        <div className="p6-mic-circle">{state.recordStatus === 'thinking' ? '💭' : '🎤'}</div>
      </div>

      {/* animated waveform — only while actually recording */}
      {live && (
        <div className="p6-waveform">
          {Array.from({ length: BAR_COUNT }).map((_, i) => (
            <div
              key={i}
              className="p6-bar"
              style={{
                animationDelay: `${DELAYS[i]}s`,
                animationDuration: `${DURATIONS[i]}s`,
              }}
            />
          ))}
        </div>
      )}

      <div className="p6-label">{statusLabel(state.recordStatus, state.recording, state.caption)}</div>
    </div>
  )
}
