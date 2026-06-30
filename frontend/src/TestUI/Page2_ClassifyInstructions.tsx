import { HumanoidTPose, HumanoidCrossedArms, RobotTPose, CameraIcon } from './Characters'
import { DummyStream } from './DummyStream'

const steps = [
  {
    num: 1,
    label: 'Do your favorite pose!',
    art: <HumanoidTPose width={100} />,
  },
  {
    num: 2,
    label: 'Coral takes a picture',
    art: <CameraIcon width={90} />,
  },
  {
    num: 3,
    label: 'Coral matches your pose!',
    art: <RobotTPose width={110} />,
  },
  {
    num: 4,
    label: 'Cross your arms when ready',
    art: <HumanoidCrossedArms width={100} />,
  },
]

export default function Page2_ClassifyInstructions() {
  return (
    <div className="p2-layout tui-page" style={{ position: 'relative' }}>
      <div className="p2-title">How it works!</div>

      <div className="p2-steps">
        {steps.map((s) => (
          <div className="p2-step" key={s.num}>
            <div className="p2-step-num">{s.num}</div>
            <div className="p2-step-art">{s.art}</div>
            <div className="p2-step-label">{s.label}</div>
          </div>
        ))}
      </div>

      {/* Mini live stream bottom-left */}
      <DummyStream
        className="p2-mini-stream tui-card"
        style={{ position: 'absolute', bottom: 16, left: 16, width: 120, height: 84, borderRadius: 14, border: '3px solid white' }}
        showPerson
        personWidth={60}
      />
    </div>
  )
}
