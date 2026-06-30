import { DummyFrame } from './DummyStream'

const DUMMY_RESULTS = [
  { label: 'T-Pose', pct: 91, top: true },
  { label: 'Superhero', pct: 5, top: false },
  { label: 'Warrior 2', pct: 3, top: false },
  { label: 'Dab', pct: 1, top: false },
]

export default function Page4_ClassifyResults() {
  return (
    <div className="tui-page p4-layout">
      {/* Full-screen captured frame */}
      <DummyFrame style={{ position: 'absolute', inset: 0 }} />

      {/* Result overlay at bottom */}
      <div className="p4-result-bar">
        <div className="p4-class-name">🎯 T-Pose!</div>
        <div className="p4-bars">
          {DUMMY_RESULTS.map((r, i) => (
            <div className="p4-bar-row" key={r.label} style={{ animationDelay: `${0.1 + i * 0.12}s` }}>
              <span className="p4-bar-label">{r.label}</span>
              <div className="p4-bar-track">
                <div
                  className={`p4-bar-fill ${r.top ? 'top' : ''}`}
                  style={{ width: `${r.pct}%`, transition: `width ${0.8 + i * 0.1}s cubic-bezier(0.2,1,0.3,1)` }}
                />
              </div>
              <span className="p4-bar-pct">{r.pct}%</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
