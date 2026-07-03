import React from 'react'

interface CharProps {
  width?: number
  className?: string
  style?: React.CSSProperties
}

/* Neutral mannequin palette — no race, no clothes */
const HF = '#EAE5DE'   // body fill (warm white)
const HS = '#B5AFA5'   // body stroke
const HD = '#3D3530'   // eyes / mouth

/* ── Shared face pieces ─────────────────────────────────────────────────── */
function HumanFace() {
  return (
    <>
      {/* head */}
      <circle cx="50" cy="28" r="22" fill={HF} stroke={HS} strokeWidth="1.5" />
      {/* eyes */}
      <circle cx="42" cy="26" r="3.5" fill={HD} />
      <circle cx="58" cy="26" r="3.5" fill={HD} />
      {/* smile */}
      <path d="M42 34 Q50 42 58 34" stroke={HD} strokeWidth="2.5" fill="none" strokeLinecap="round" />
    </>
  )
}

function HumanBody() {
  return (
    <>
      {/* neck */}
      <rect x="44" y="48" width="12" height="10" rx="4" fill={HF} />
      {/* torso */}
      <rect x="27" y="56" width="46" height="44" rx="14" fill={HF} stroke={HS} strokeWidth="1.5" />
      {/* left leg */}
      <rect x="28" y="97" width="18" height="48" rx="9" fill={HF} stroke={HS} strokeWidth="1.5" />
      {/* right leg */}
      <rect x="54" y="97" width="18" height="48" rx="9" fill={HF} stroke={HS} strokeWidth="1.5" />
      {/* left foot */}
      <ellipse cx="37" cy="148" rx="13" ry="6.5" fill={HF} stroke={HS} strokeWidth="1.5" />
      {/* right foot */}
      <ellipse cx="63" cy="148" rx="13" ry="6.5" fill={HF} stroke={HS} strokeWidth="1.5" />
    </>
  )
}

/* ── Humanoid: standing, arms relaxed ──────────────────────────────────── */
export function HumanoidIdle({ width = 120, className = '', style }: CharProps) {
  return (
    <svg viewBox="0 0 100 160" width={width} className={`tui-bob ${className}`} style={style}>
      <HumanFace />
      <HumanBody />
      {/* left arm — outline then fill */}
      <path d="M28 68 L16 100" stroke={HS} strokeWidth="16" strokeLinecap="round" fill="none" />
      <path d="M28 68 L16 100" stroke={HF} strokeWidth="13" strokeLinecap="round" fill="none" />
      <circle cx="15" cy="103" r="7" fill={HF} stroke={HS} strokeWidth="1.5" />
      {/* right arm — outline then fill */}
      <path d="M72 68 L84 100" stroke={HS} strokeWidth="16" strokeLinecap="round" fill="none" />
      <path d="M72 68 L84 100" stroke={HF} strokeWidth="13" strokeLinecap="round" fill="none" />
      <circle cx="85" cy="103" r="7" fill={HF} stroke={HS} strokeWidth="1.5" />
    </svg>
  )
}

/* ── Humanoid: arms crossed in X ────────────────────────────────────────── */
export function HumanoidCrossedArms({ width = 120, className = '', style }: CharProps) {
  return (
    <svg viewBox="0 0 100 160" width={width} className={`tui-float ${className}`} style={style}>
      <HumanFace />
      <HumanBody />
      {/* outlines first (both arms), then fills — preserves left-over-right layering */}
      <path d="M72 65 Q50 80 26 94" stroke={HS} strokeWidth="16" strokeLinecap="round" fill="none" />
      <path d="M28 65 Q50 80 74 94" stroke={HS} strokeWidth="16" strokeLinecap="round" fill="none" />
      <path d="M72 65 Q50 80 26 94" stroke={HF} strokeWidth="13" strokeLinecap="round" fill="none" />
      <path d="M28 65 Q50 80 74 94" stroke={HF} strokeWidth="13" strokeLinecap="round" fill="none" />
      {/* hand tips */}
      <circle cx="26" cy="94" r="6" fill={HF} stroke={HS} strokeWidth="1.5" />
      <circle cx="74" cy="94" r="6" fill={HF} stroke={HS} strokeWidth="1.5" />
    </svg>
  )
}

/* ── Humanoid: T-pose (arms out) ─────────────────────────────────────────── */
export function HumanoidTPose({ width = 130, className = '', style }: CharProps) {
  return (
    <svg viewBox="-10 -2 150 164" width={width} className={`tui-bob ${className}`} style={style}>
      {/* shift everything right to accommodate wide arms */}
      <g transform="translate(15, 0)">
        <HumanFace />
        <HumanBody />
        {/* left arm horizontal — outline then fill */}
        <path d="M27 68 L-10 68" stroke={HS} strokeWidth="16" strokeLinecap="round" fill="none" />
        <path d="M27 68 L-10 68" stroke={HF} strokeWidth="13" strokeLinecap="round" fill="none" />
        <circle cx="-11" cy="68" r="7" fill={HF} stroke={HS} strokeWidth="1.5" />
        {/* right arm horizontal — outline then fill */}
        <path d="M73 68 L110 68" stroke={HS} strokeWidth="16" strokeLinecap="round" fill="none" />
        <path d="M73 68 L110 68" stroke={HF} strokeWidth="13" strokeLinecap="round" fill="none" />
        <circle cx="111" cy="68" r="7" fill={HF} stroke={HS} strokeWidth="1.5" />
      </g>
    </svg>
  )
}

/* ── Humanoid: speaking pose (one hand up) ───────────────────────────────── */
export function HumanoidSpeaking({ width = 100, className = '', style }: CharProps) {
  return (
    <svg viewBox="0 0 100 160" width={width} className={`tui-bob ${className}`} style={style}>
      <HumanFace />
      <HumanBody />
      {/* left arm down — outline then fill */}
      <path d="M28 68 L16 100" stroke={HS} strokeWidth="16" strokeLinecap="round" fill="none" />
      <path d="M28 68 L16 100" stroke={HF} strokeWidth="13" strokeLinecap="round" fill="none" />
      <circle cx="15" cy="103" r="7" fill={HF} stroke={HS} strokeWidth="1.5" />
      {/* right arm raised — outline then fill */}
      <path d="M72 68 L86 40" stroke={HS} strokeWidth="16" strokeLinecap="round" fill="none" />
      <path d="M72 68 L86 40" stroke={HF} strokeWidth="13" strokeLinecap="round" fill="none" />
      <circle cx="87" cy="38" r="7" fill={HF} stroke={HS} strokeWidth="1.5" />
    </svg>
  )
}

/* ── Shared robot pieces ─────────────────────────────────────────────────── */
function RobotBase({ rightArm }: { rightArm: React.ReactNode }) {
  return (
    <>
      {/* antenna */}
      <line x1="50" y1="5" x2="50" y2="18" stroke="#90A4AE" strokeWidth="3" strokeLinecap="round" />
      <circle cx="50" cy="4" r="5" fill="#FF6B9D" className="tui-glow" />
      {/* head */}
      <rect x="22" y="18" width="56" height="40" rx="10" fill="#90A4AE" stroke="#607D8B" strokeWidth="2" />
      {/* screen */}
      <rect x="30" y="24" width="40" height="28" rx="6" fill="#0D1B2A" />
      {/* eye */}
      <circle cx="50" cy="38" r="10" fill="#1565C0" />
      <circle cx="50" cy="38" r="5.5" fill="#42A5F5" />
      <circle cx="54" cy="34" r="2.5" fill="white" opacity="0.8" />
      {/* head bolts */}
      <circle cx="26" cy="22" r="2" fill="#607D8B" />
      <circle cx="74" cy="22" r="2" fill="#607D8B" />
      {/* body */}
      <rect x="22" y="62" width="56" height="52" rx="10" fill="#78909C" stroke="#607D8B" strokeWidth="2" />
      {/* chest light */}
      <circle cx="50" cy="80" r="7" fill="#FF6B9D" className="tui-glow" />
      <circle cx="50" cy="80" r="7" fill="none" stroke="#FF6B9D" strokeWidth="4" opacity="0.35" />
      {/* body vents */}
      <rect x="34" y="98" width="32" height="3" rx="1.5" fill="#607D8B" />
      <rect x="34" y="106" width="32" height="3" rx="1.5" fill="#607D8B" />
      {/* left arm */}
      <rect x="4" y="64" width="16" height="42" rx="7" fill="#90A4AE" stroke="#607D8B" strokeWidth="1.5" />
      <rect x="2" y="108" width="18" height="12" rx="5" fill="#78909C" />
      {/* right arm (slot for variant) */}
      {rightArm}
      {/* legs */}
      <rect x="26" y="116" width="18" height="44" rx="8" fill="#78909C" stroke="#607D8B" strokeWidth="1.5" />
      <rect x="56" y="116" width="18" height="44" rx="8" fill="#78909C" stroke="#607D8B" strokeWidth="1.5" />
      {/* feet */}
      <rect x="18" y="154" width="28" height="12" rx="5" fill="#607D8B" />
      <rect x="54" y="154" width="28" height="12" rx="5" fill="#607D8B" />
    </>
  )
}

/* ── Robot: standing idle ────────────────────────────────────────────────── */
export function RobotIdle({ width = 120, className = '', style }: CharProps) {
  const rightArm = (
    <>
      <rect x="80" y="64" width="16" height="42" rx="7" fill="#90A4AE" stroke="#607D8B" strokeWidth="1.5" />
      <rect x="80" y="108" width="18" height="12" rx="5" fill="#78909C" />
    </>
  )
  return (
    <svg viewBox="0 0 100 175" width={width} className={`tui-bob ${className}`} style={style}>
      <RobotBase rightArm={rightArm} />
    </svg>
  )
}

/* ── Robot: waving (CSS animates the arm group) ──────────────────────────── */
export function RobotWaving({ width = 130, className = '', style }: CharProps) {
  const rightArm = (
    // Layer 1: position at shoulder — parent SVG transform, CSS animation won't override it
    <g transform="translate(88, 64)">
      {/* Layer 2: static pre-rotate to raise arm into up-right wave position (130° CCW from down) */}
      <g transform="rotate(-130)">
        {/* Layer 3: CSS oscillation only — pivots around top of arm (shoulder) */}
        <g
          style={{ transformBox: 'fill-box' as const, transformOrigin: '50% 0%' }}
          className="tui-wave-arm-anim"
        >
          <rect x="-8" y="0" width="16" height="42" rx="7" fill="#90A4AE" stroke="#607D8B" strokeWidth="1.5" />
          <rect x="-9" y="43" width="18" height="12" rx="5" fill="#78909C" />
        </g>
      </g>
    </g>
  )
  return (
    <svg viewBox="0 0 100 175" width={width} className={`tui-bob ${className}`} style={style}>
      <RobotBase rightArm={rightArm} />
    </svg>
  )
}

/* ── Robot: T-pose (mimicking human) ─────────────────────────────────────── */
export function RobotTPose({ width = 140, className = '', style }: CharProps) {
  return (
    <svg viewBox="-20 0 180 175" width={width} className={`tui-bob ${className}`} style={style}>
      <g transform="translate(20, 0)">
        {/* antenna */}
        <line x1="50" y1="5" x2="50" y2="18" stroke="#90A4AE" strokeWidth="3" strokeLinecap="round" />
        <circle cx="50" cy="4" r="5" fill="#FF6B9D" />
        {/* head */}
        <rect x="22" y="18" width="56" height="40" rx="10" fill="#90A4AE" stroke="#607D8B" strokeWidth="2" />
        <rect x="30" y="24" width="40" height="28" rx="6" fill="#0D1B2A" />
        <circle cx="50" cy="38" r="10" fill="#1565C0" />
        <circle cx="50" cy="38" r="5.5" fill="#42A5F5" />
        <circle cx="54" cy="34" r="2.5" fill="white" opacity="0.8" />
        {/* body */}
        <rect x="22" y="62" width="56" height="52" rx="10" fill="#78909C" stroke="#607D8B" strokeWidth="2" />
        <circle cx="50" cy="80" r="7" fill="#FF6B9D" />
        {/* left arm horizontal */}
        <rect x="-32" y="66" width="52" height="14" rx="6" fill="#90A4AE" stroke="#607D8B" strokeWidth="1.5" />
        <rect x="-34" y="64" width="16" height="18" rx="6" fill="#78909C" />
        {/* right arm horizontal */}
        <rect x="78" y="66" width="52" height="14" rx="6" fill="#90A4AE" stroke="#607D8B" strokeWidth="1.5" />
        <rect x="116" y="64" width="16" height="18" rx="6" fill="#78909C" />
        {/* legs */}
        <rect x="26" y="116" width="18" height="44" rx="8" fill="#78909C" stroke="#607D8B" strokeWidth="1.5" />
        <rect x="56" y="116" width="18" height="44" rx="8" fill="#78909C" stroke="#607D8B" strokeWidth="1.5" />
        <rect x="18" y="154" width="28" height="12" rx="5" fill="#607D8B" />
        <rect x="54" y="154" width="28" height="12" rx="5" fill="#607D8B" />
      </g>
    </svg>
  )
}

/* ── Camera icon ─────────────────────────────────────────────────────────── */
export function CameraIcon({ width = 90, className = '', style }: CharProps) {
  return (
    <svg viewBox="0 0 100 80" width={width} className={className} style={style}>
      {/* flash rings */}
      <circle cx="50" cy="45" r="38" fill="none" stroke="#f7c43e" strokeWidth="3" opacity="0.3"
        style={{ animation: 'tui-mic-ring 2s ease-out infinite' }} />
      <circle cx="50" cy="45" r="28" fill="none" stroke="#f7c43e" strokeWidth="3" opacity="0.5"
        style={{ animation: 'tui-mic-ring 2s 0.6s ease-out infinite' }} />
      {/* body */}
      <rect x="12" y="25" width="76" height="50" rx="12" fill="#f7c43e" stroke="#b8861c" strokeWidth="2" />
      {/* viewfinder bump */}
      <rect x="36" y="16" width="28" height="14" rx="6" fill="#f7c43e" stroke="#b8861c" strokeWidth="2" />
      {/* lens ring */}
      <circle cx="50" cy="50" r="18" fill="white" stroke="#b8861c" strokeWidth="2" />
      <circle cx="50" cy="50" r="12" fill="#1565C0" />
      <circle cx="50" cy="50" r="6" fill="#42A5F5" />
      <circle cx="53" cy="47" r="2.5" fill="white" opacity="0.7" />
      {/* flash */}
      <rect x="74" y="30" width="8" height="6" rx="3" fill="white" opacity="0.8" />
    </svg>
  )
}
