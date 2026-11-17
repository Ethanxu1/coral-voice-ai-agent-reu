/**
 * Test-page switch for the sim's upright pin. Off (default): the robot's body
 * is held upright and can't fall. On: normal physics, so it can tip over.
 */
export default function GravityToggle({
  gravity,
  onChange,
  disabled = false,
}: {
  gravity: boolean
  onChange: (gravity: boolean) => void
  disabled?: boolean
}) {
  return (
    <label
      title="Off: the sim robot is held upright and can't fall. On: normal physics, so it can tip over."
      style={{ display: 'inline-flex', alignItems: 'center', gap: 4, cursor: 'pointer', whiteSpace: 'nowrap' }}
    >
      <input type="checkbox" checked={gravity} onChange={(e) => onChange(e.target.checked)} disabled={disabled} />
      Gravity (robot can fall)
    </label>
  )
}
