import { Link, useNavigate } from 'react-router-dom'
import { GESTURES_PATH } from '../gestures/GestureTopbar'
import { useGestures } from '../gestures/library'
import './RefinedDemo.css'
import './RockPaperScissors.css'
import './GestureStudio.css'

/** Landing screen for Gesture Studio: record new gestures or browse the library. */
export default function GestureStudio() {
  const navigate = useNavigate()
  const count = useGestures().length
  return (
    <div className="rd-root">
      <header className="rd-topbar">
        <div className="rd-topbar-left">
          <div className="rd-logo">
            coral<span>.</span>
          </div>
        </div>
        <div className="rd-topbar-right">
          <button className="rd-topbar-btn danger" onClick={() => navigate('/')}>
            End
          </button>
        </div>
      </header>

      <main className="rps-menu">
        <h1 className="rps-menu-title">Gesture Studio</h1>
        <p className="rps-menu-sub">Teach CORAL new gestures and fine-tune how it performs them.</p>
        <div className="rps-menu-cards gs-menu-cards">
          <Link to={`${GESTURES_PATH}/record`} className="rps-menu-card play">
            <span className="rps-menu-emoji">🎥</span>
            <span className="rps-menu-name">Record gestures</span>
            <span className="rps-menu-desc">Strike a pose in front of the camera and hold it for 1.5 seconds to save it.</span>
          </Link>
          <Link to={`${GESTURES_PATH}/library`} className="rps-menu-card learn">
            <span className="rps-menu-emoji">🗂️</span>
            <span className="rps-menu-name">Gesture library</span>
            <span className="rps-menu-desc">
              {count === 0 ? 'No gestures yet.' : `${count} gesture${count === 1 ? '' : 's'} saved.`} View, fine-tune,
              import and export them.
            </span>
          </Link>
        </div>
      </main>
    </div>
  )
}
