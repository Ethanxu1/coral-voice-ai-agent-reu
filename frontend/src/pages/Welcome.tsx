import { useNavigate } from 'react-router-dom'
import './CoralMessage.css'

// First screen of the demo. Coral introduces itself and offers to run the
// tutorial or jump straight to the home page (the live demo).
export default function Welcome() {
  const navigate = useNavigate()

  return (
    <div className="cm-root">
      <div className="cm-logo">
        coral<span>.</span>
      </div>

      <div className="cm-center">
        <div className="cm-card">
          <div className="cm-avatar">🪸</div>
          <div className="cm-eyebrow">Welcome</div>
          <p className="cm-message">
            Hi there! My name is Coral, and I am a robot who loves to learn new
            poses. If you would like, we can do a tutorial together showing what
            I can and can’t do!
          </p>
          <div className="cm-btns">
            <button
              className="cm-btn primary"
              onClick={() => navigate('/tutorial')}
            >
              📚 Let’s do the tutorial
            </button>
            <button
              className="cm-btn secondary"
              onClick={() => navigate('/home', { state: { fromApp: true } })}
            >
              Skip to the lesson →
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
