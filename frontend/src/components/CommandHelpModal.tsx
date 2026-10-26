import type { IntentExamples } from '../api/robot'

/** "What can I say?" palette: tap a phrase to send it as if spoken. */
export default function CommandHelpModal({
  examples,
  onSelect,
  onClose,
}: {
  examples: IntentExamples
  onSelect: (text: string) => void
  onClose: () => void
}) {
  return (
    <div className="rd-overlay" onClick={onClose}>
      <div className="rd-overlay-card rd-command-card" onClick={(e) => e.stopPropagation()}>
        <div className="rd-overlay-title">What can I say?</div>
        <div className="rd-command-sections">
          <CommandSection title="Move my body" icon="🦾" phrases={examples.motion} onSelect={onSelect} />
          <CommandSection title="Play with poses" icon="🤸" phrases={examples.immediate} onSelect={onSelect} />
          <CommandSection title="Chat" icon="💬" phrases={examples.conversation} onSelect={onSelect} />
        </div>
        <div className="rd-overlay-btns">
          <button className="rd-overlay-btn secondary" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  )
}

function CommandSection({
  title,
  icon,
  phrases,
  onSelect,
}: {
  title: string
  icon: string
  phrases: string[]
  onSelect: (text: string) => void
}) {
  if (!phrases.length) return null
  return (
    <div className="rd-command-section">
      <div className="rd-command-section-title">
        <span>{icon}</span> {title}
      </div>
      <div className="rd-command-chips">
        {phrases.map((phrase) => (
          <button key={phrase} className="rd-command-chip" onClick={() => onSelect(phrase)}>
            {phrase}
          </button>
        ))}
      </div>
    </div>
  )
}
