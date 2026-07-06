import { useState } from 'react'

/** Inline text-entry box used on the record/name pages when input mode is 'text'
 * (replaces the microphone visual). Submits the trimmed value on click or Enter. */
export function TextEntry({
  prompt,
  placeholder = 'Type here…',
  onSubmit,
}: {
  prompt: string
  placeholder?: string
  onSubmit: (text: string) => void
}) {
  const [value, setValue] = useState('')
  const submit = () => {
    const v = value.trim()
    if (v) {
      onSubmit(v)
      setValue('')
    }
  }
  return (
    <div className="tui-text-entry tui-pop">
      <div className="tui-text-entry-prompt">{prompt}</div>
      <input
        className="tui-text-input"
        autoFocus
        value={value}
        placeholder={placeholder}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter') submit() }}
      />
      <button className="tui-btn tui-btn-go" onClick={submit}>Submit</button>
    </div>
  )
}
