import { HumanoidSpeaking } from './Characters'

/* Robot with right arm slightly raised to show "adjusting" */
function RobotArmAdjusted() {
  return (
    <svg viewBox="0 0 100 175" width={110} className="tui-bob">
      {/* same as RobotIdle but right arm angle shifted */}
      <line x1="50" y1="5" x2="50" y2="18" stroke="#90A4AE" strokeWidth="3" strokeLinecap="round" />
      <circle cx="50" cy="4" r="5" fill="#FF6B9D" className="tui-glow" />
      <rect x="22" y="18" width="56" height="40" rx="10" fill="#90A4AE" stroke="#607D8B" strokeWidth="2" />
      <rect x="30" y="24" width="40" height="28" rx="6" fill="#0D1B2A" />
      <circle cx="50" cy="38" r="10" fill="#1565C0" />
      <circle cx="50" cy="38" r="5.5" fill="#42A5F5" />
      <circle cx="54" cy="34" r="2.5" fill="white" opacity="0.8" />
      <rect x="22" y="62" width="56" height="52" rx="10" fill="#78909C" stroke="#607D8B" strokeWidth="2" />
      <circle cx="50" cy="80" r="7" fill="#FF6B9D" />
      <rect x="34" y="98" width="32" height="3" rx="1.5" fill="#607D8B" />
      <rect x="34" y="106" width="32" height="3" rx="1.5" fill="#607D8B" />
      {/* left arm down */}
      <rect x="4" y="64" width="16" height="42" rx="7" fill="#90A4AE" stroke="#607D8B" strokeWidth="1.5" />
      <rect x="2" y="108" width="18" height="12" rx="5" fill="#78909C" />
      {/* right arm — pre-raised to ~2 o'clock, then gently oscillates downward */}
      <g transform="translate(88, 64)">
        <g transform="rotate(-110)">
          <g
            style={{ transformBox: 'fill-box' as const, transformOrigin: '50% 0%' }}
            className="tui-adjust-arm-anim"
          >
            <rect x="-8" y="0" width="16" height="42" rx="7" fill="#90A4AE" stroke="#607D8B" strokeWidth="1.5" />
            <rect x="-9" y="43" width="18" height="12" rx="5" fill="#78909C" />
          </g>
        </g>
      </g>
      {/* legs */}
      <rect x="26" y="116" width="18" height="44" rx="8" fill="#78909C" stroke="#607D8B" strokeWidth="1.5" />
      <rect x="56" y="116" width="18" height="44" rx="8" fill="#78909C" stroke="#607D8B" strokeWidth="1.5" />
      <rect x="18" y="154" width="28" height="12" rx="5" fill="#607D8B" />
      <rect x="54" y="154" width="28" height="12" rx="5" fill="#607D8B" />
    </svg>
  )
}

export default function Page5_RecordInstructions() {
  return (
    <div className="tui-page p5-layout">
      <div className="p5-title">Tell Coral how to fix it!</div>

      <div className="p5-steps">
        {/* Step 1 — child speaks */}
        <div className="p5-step">
          <div className="p5-step-num">1</div>
          <div className="p5-step-art">
            <HumanoidSpeaking width={90} />
            <div className="tui-bubble">
              "Move your right arm a little lower"
            </div>
          </div>
          <div className="p5-step-label">You give Coral a hint with your voice</div>
        </div>

        {/* Step 2 — robot adjusts */}
        <div className="p5-step">
          <div className="p5-step-num">2</div>
          <div className="p5-step-art" style={{ flexDirection: 'column', gap: 6 }}>
            <RobotArmAdjusted />
            {/* small arrow indicator */}
            <div style={{
              background: 'linear-gradient(135deg,#6a5acd,#ff6b9d)',
              color: 'white',
              borderRadius: 999,
              padding: '4px 14px',
              fontSize: 12,
              fontWeight: 800,
            }}>
              ↓ arm lowers
            </div>
          </div>
          <div className="p5-step-label">Coral adjusts to match you better!</div>
        </div>
      </div>
    </div>
  )
}
