import { useNavigate } from 'react-router-dom'
import { ConnectionHealthDot, useConnectionStatus } from '../components/ConnectionStatus'
import { resetRobot } from './robotPose'

export const RPS_PATH = '/rock-paper-scissors'

/** Top bar shared by the Rock-Paper-Scissors screens. */
export default function RpsTopbar({ busy = false }: { busy?: boolean }) {
  const navigate = useNavigate()
  const services = useConnectionStatus()
  return (
    <header className="rd-topbar">
      <div className="rd-topbar-left">
        <div className="rd-logo">
          coral<span>.</span>
        </div>
      </div>
      <div className="rd-topbar-right">
        <button className="rd-topbar-btn ghost" onClick={() => !busy && navigate(RPS_PATH)}>
          Menu
        </button>
        <button className="rd-topbar-btn ghost" onClick={() => { resetRobot().catch(() => {}) }}>
          Return to stand
        </button>
        <ConnectionHealthDot services={services} />
        <button className="rd-topbar-btn danger" onClick={() => navigate('/')}>
          End
        </button>
      </div>
    </header>
  )
}
