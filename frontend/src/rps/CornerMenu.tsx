import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ConnectionHealthDot, useConnectionStatus } from '../components/ConnectionStatus'
import { RPS_PATH } from './RpsTopbar'

/** How long a leave button must be held, so a child can't end the game by accident. */
const HOLD_MS = 1200

/** A button that fires only after being held down for HOLD_MS; a ring fills while it is held. */
function HoldButton({ label, onDone }: { label: string; onDone: () => void }) {
  const [holding, setHolding] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout>>()
  const stop = () => {
    clearTimeout(timer.current)
    setHolding(false)
  }
  const start = () => {
    setHolding(true)
    timer.current = setTimeout(onDone, HOLD_MS)
  }
  useEffect(() => () => clearTimeout(timer.current), [])
  return (
    <button
      className={`cm-item hold ${holding ? 'holding' : ''}`}
      style={{ '--hold': `${HOLD_MS}ms` } as React.CSSProperties}
      onPointerDown={start}
      onPointerUp={stop}
      onPointerLeave={stop}
      onPointerCancel={stop}
    >
      <span className="fill" />
      <span className="txt">{label}</span>
      <small>hold</small>
    </button>
  )
}

/**
 * The grown-ups' controls, folded into one small icon in the corner: connection,
 * how to play, and press-and-hold buttons to leave the game.
 */
export default function CornerMenu({ onHelp }: { onHelp: () => void }) {
  const navigate = useNavigate()
  const services = useConnectionStatus()
  const [open, setOpen] = useState(false)
  return (
    <div className="corner-menu">
      <button className="cm-toggle" aria-label="Grown-up menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden>
          <circle cx="5" cy="12" r="2.2" fill="currentColor" />
          <circle cx="12" cy="12" r="2.2" fill="currentColor" />
          <circle cx="19" cy="12" r="2.2" fill="currentColor" />
        </svg>
      </button>
      {open && (
        <div className="cm-pop">
          <div className="cm-status">
            <ConnectionHealthDot services={services} />
          </div>
          <button
            className="cm-item"
            onClick={() => {
              setOpen(false)
              onHelp()
            }}
          >
            How to play
          </button>
          <HoldButton label="Game menu" onDone={() => navigate(RPS_PATH)} />
          <HoldButton label="Exit" onDone={() => navigate('/')} />
        </div>
      )}
    </div>
  )
}
