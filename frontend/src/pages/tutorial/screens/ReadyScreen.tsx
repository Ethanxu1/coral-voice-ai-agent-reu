import { RobotIllustration, Confetti } from '../parts'
import { ROBOT_NAME } from '../state'

export function ReadyScreen({ onMeetRobot }: { onMeetRobot: () => void }) {
  return (
    <div className="tut-ready">
      <Confetti />
      <div className="tut-ready-stars">
        <span style={{ fontSize: 26 }}>★</span>
        <span className="tut-ready-title">You did it!</span>
        <span style={{ fontSize: 26 }}>★</span>
      </div>
      <div className="tut-ready-robot">
        <RobotIllustration wave happy />
      </div>
      <div className="tut-ready-msg">
        <div className="tut-ready-msg-title">You taught {ROBOT_NAME} really well in there.</div>
        <div className="tut-ready-msg-sub">Ready to try with the real robot?</div>
      </div>
      <button className="tut-ready-cta" onClick={onMeetRobot}>
        Meet the real {ROBOT_NAME}! →
      </button>
    </div>
  )
}
