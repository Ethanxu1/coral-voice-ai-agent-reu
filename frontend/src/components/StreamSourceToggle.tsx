import { setRobotConfig, useRobotConfig } from '../demo/robotConfig'

export default function StreamSourceToggle({ compact = false }: { compact?: boolean }) {
  const { streamSource } = useRobotConfig()

  return (
    <div className={`stream-source-toggle ${compact ? 'compact' : ''}`}>
      <span className="stream-source-label">Stream</span>
      <div className="stream-source-switch">
        <button
          className={streamSource === 'mac' ? 'active' : ''}
          onClick={() => setRobotConfig({ streamSource: 'mac' })}
        >
          Mac
        </button>
        <button
          className={streamSource === 'robot' ? 'active' : ''}
          onClick={() => setRobotConfig({ streamSource: 'robot' })}
        >
          Robot
        </button>
      </div>
    </div>
  )
}
