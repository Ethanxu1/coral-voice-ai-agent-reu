import { useNavigate } from 'react-router-dom'
import './CoralMessage.css'

// First screen of the demo. Coral introduces itself and offers to run the
// tutorial or jump straight to the live demo.
export default function Welcome() {
  const navigate = useNavigate()

  const steps = [
    { emoji: '🗣️', text: 'Talk or tap a command' },
    { emoji: '🤖', text: 'Watch Coral move in the simulator' },
    { emoji: '📸', text: 'Teach Coral a pose' },
  ]

  return (
    <div className="cm-root">
      <div className="cm-logo">
        coral<span>.</span>
      </div>

      <div className="cm-center">
        <div className="cm-card cm-welcome-card">
          <div className="cm-avatar">🪸</div>
          <div className="cm-eyebrow">Welcome</div>
          <p className="cm-message cm-welcome-message">
            Hi there! My name is Coral, and I am a robot who loves to learn new
            poses. Here is how we will play together:
          </p>

          <div className="cm-steps">
            {steps.map((step, i) => (
              <div key={i} className="cm-step">
                <div className="cm-step-number">{i + 1}</div>
                <div className="cm-step-emoji">{step.emoji}</div>
                <div className="cm-step-text">{step.text}</div>
              </div>
            ))}
          </div>

          <div className="cm-btns cm-welcome-btns">
            <button
              className="cm-btn primary cm-btn-large"
              onClick={() => navigate('/home', { state: { fromApp: true } })}
            >
              Start playing →
            </button>
            <button
              className="cm-btn secondary"
              onClick={() => navigate('/tutorial')}
            >
              📚 Show me the tutorial first
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
