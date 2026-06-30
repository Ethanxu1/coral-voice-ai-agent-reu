const BAR_COUNT = 14
const DELAYS = [0, 0.18, 0.36, 0.08, 0.55, 0.28, 0.70, 0.12, 0.44, 0.62, 0.22, 0.50, 0.34, 0.76]
const DURATIONS = [0.8, 1.1, 0.7, 1.3, 0.9, 1.0, 0.75, 1.2, 0.85, 1.05, 0.95, 0.65, 1.15, 0.9]

export default function Page6_RecordMic() {
  return (
    <div className="tui-page p6-layout">
      {/* pulsing ring + mic */}
      <div className="p6-mic-wrap">
        <div className="p6-ring" />
        <div className="p6-ring" />
        <div className="p6-ring" />
        <div className="p6-mic-circle">🎤</div>
      </div>

      {/* animated waveform */}
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

      <div className="p6-label">Listening…</div>
    </div>
  )
}
