import { RobotIllustration } from '../parts'
import { ROBOT_NAME } from '../state'

export function WelcomeScreen({ onStart, onSkip }: { onStart: () => void; onSkip: () => void }) {
  return (
    <div className="tut-welcome">
      <div className="tut-welcome-grid" />
      <div className="tut-welcome-logo">
        <div className="tut-logo-box">
          <div className="tut-logo-diamond" />
        </div>
        <div>
          <div className="tut-logo-name">{ROBOT_NAME}</div>
          <div className="tut-logo-sub">TUTORIAL</div>
        </div>
      </div>
      <div className="tut-welcome-robot">
        <RobotIllustration />
      </div>
      <div className="tut-welcome-bubble">
        <div className="tut-welcome-title">
          Hey! I'm {ROBOT_NAME}'s helper. Today, <span style={{ color: 'var(--accent)' }}>YOU</span> get to be the robot teacher.
        </div>
        <div className="tut-welcome-sub">Before we meet the real robot, let's practice in the simulator first.</div>
      </div>
      <div className="tut-welcome-btns">
        <button className="tut-welcome-cta" onClick={onStart}>
          Let's explore!
        </button>
        <button className="tut-welcome-skip" onClick={onSkip}>
          Skip →
        </button>
      </div>
    </div>
  )
}
