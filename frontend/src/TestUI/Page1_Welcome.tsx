import { DummyStream } from './DummyStream'
import { HumanoidCrossedArms } from './Characters'

export default function Page1_Welcome() {
  return (
    <div className="tui-page p1-layout">
      {/* Left — live feed */}
      <DummyStream className="p1-stream" />

      {/* Right — welcome panel */}
      <div className="p1-panel">
        <div className="p1-welcome tui-pop">👋 Welcome!</div>

        <HumanoidCrossedArms width={180} />

        <div className="p1-instruction tui-pop" style={{ animationDelay: '0.15s' }}>
          Cross your arms like an&nbsp;
          <strong>X</strong>
          <br />when you are ready to continue!
        </div>
      </div>
    </div>
  )
}
