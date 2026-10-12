import { useNavigate } from 'react-router-dom'
import { ConnectionHealthDot } from '../pages/RefinedDemo'
import { useConnectionStatus } from '../components/ConnectionStatus'
import { resetRobot } from '../rps/robotPose'

export const GESTURES_PATH = '/gestures'

/** Top bar shared by the Gesture Studio screens. */
export default function GestureTopbar({ title, busy = false }: { title?: string; busy?: boolean }) {
  const navigate = useNavigate()
  const services = useConnectionStatus()
  return (
    <header className="rd-topbar">
      <div className="rd-topbar-left">
        <div className="rd-logo">
          coral<span>.</span>
        </div>
        {title && <div className="gs-topbar-title">{title}</div>}
      </div>
      <div className="rd-topbar-right">
        <button className="rd-topbar-btn ghost" onClick={() => !busy && navigate(GESTURES_PATH)}>
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
