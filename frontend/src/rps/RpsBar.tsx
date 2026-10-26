import type { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { ConnectionHealthDot, useConnectionStatus } from '../components/ConnectionStatus'
import { RPS_PATH } from './RpsTopbar'

/**
 * Top bar of the Play and "Make your own moves" screens (styled by RpsPlay.css):
 * logo, the screen's own status (`children`), connection, Menu, End, then `actions`.
 */
export default function RpsBar({ children, actions }: { children?: ReactNode; actions?: ReactNode }) {
  const navigate = useNavigate()
  const services = useConnectionStatus()
  return (
    <header className="topbar">
      <div className="logo">
        coral<span>.</span>
      </div>
      {children}
      <div className="spacer" />
      <ConnectionHealthDot services={services} />
      <button className="btn" onClick={() => navigate(RPS_PATH)}>
        Menu
      </button>
      <button className="btn end" onClick={() => navigate('/')}>
        End
      </button>
      {actions}
    </header>
  )
}
