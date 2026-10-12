import { Link, useNavigate } from 'react-router-dom'
import { RPS_PATH } from '../rps/RpsTopbar'
import './RefinedDemo.css'
import './RockPaperScissors.css'

/** Landing screen for Rock Paper Scissors: pick Learn or Play. */
export default function RockPaperScissorsMenu() {
  const navigate = useNavigate()
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
        <h1 className="rps-menu-title">Rock Paper Scissors</h1>
        <p className="rps-menu-sub">What do you want to do?</p>
        <div className="rps-menu-cards">
          <Link to={`${RPS_PATH}/learn`} className="rps-menu-card learn">
            <span className="rps-menu-emoji">📖</span>
            <span className="rps-menu-name">Learn gestures</span>
            <span className="rps-menu-desc">See how to make rock, paper and scissors.</span>
          </Link>
          <Link to={`${RPS_PATH}/play`} className="rps-menu-card play">
            <span className="rps-menu-emoji">🎮</span>
            <span className="rps-menu-name">Let's play</span>
            <span className="rps-menu-desc">Three rounds against CORAL. Strike a pose and see who wins.</span>
          </Link>
          <Link to={`${RPS_PATH}/custom`} className="rps-menu-card custom">
            <span className="rps-menu-emoji">🎨</span>
            <span className="rps-menu-name">Make your own moves</span>
            <span className="rps-menu-desc">Invent your own rock, paper and scissors, then play with them.</span>
          </Link>
        </div>
      </main>
    </div>
  )
}
