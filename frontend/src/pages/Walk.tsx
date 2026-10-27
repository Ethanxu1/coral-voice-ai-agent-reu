import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { walkStep, walkStop } from '../demo/api'
import './RefinedDemo.css'
import './RockPaperScissors.css'
import './Walk.css'

/** Walk screen: walk the real robot forward or backward a short way, or stop it. */
export default function Walk() {
  const navigate = useNavigate()
  const [message, setMessage] = useState<string | null>(null)

  // Never leave the robot walking when this page closes.
  useEffect(() => () => void walkStop(), [])

  const walk = async (direction: 1 | -1) => {
    setMessage(null)
    const { error, note } = await walkStep(direction)
    const walking = direction > 0 ? 'Walking forward…' : 'Walking backward…'
    setMessage(error ?? (note ? `${walking} ${note}` : walking))
  }
  const stop = async () => {
    await walkStop()
    setMessage('Stopped')
  }

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
        <h1 className="rps-menu-title">Walk</h1>
        <p className="rps-menu-sub">Which way should CORAL walk?</p>
        <div className="rps-menu-cards">
          <button type="button" className="rps-menu-card walk-card forward" onClick={() => void walk(1)}>
            <span className="rps-menu-emoji">⬆️</span>
            <span className="rps-menu-name">Walk forward</span>
            <span className="rps-menu-desc">A few steps toward you.</span>
          </button>
          <button type="button" className="rps-menu-card walk-card backward" onClick={() => void walk(-1)}>
            <span className="rps-menu-emoji">⬇️</span>
            <span className="rps-menu-name">Walk backward</span>
            <span className="rps-menu-desc">A few steps back.</span>
          </button>
        </div>
        <button type="button" className="walk-stop" onClick={() => void stop()}>
          Stop
        </button>
        {message && (
          <p className="walk-message" role="status">
            {message}
          </p>
        )}
      </main>
    </div>
  )
}
