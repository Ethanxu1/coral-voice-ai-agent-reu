import './AIReasoningStepper.css'

export type StepId = 'command' | 'understanding' | 'safety' | 'clarification' | 'execute'
export type StepState = 'upcoming' | 'active' | 'success' | 'blocked' | 'skipped'

export interface StepItem {
  id: StepId
  label: string
  state: StepState
  detail?: string
  action?: { label: string; onClick: () => void }
}

interface AIReasoningStepperProps {
  steps: StepItem[]
}

const STEP_ORDER: StepId[] = ['command', 'understanding', 'safety', 'clarification', 'execute']

function StepIcon({ state, num }: { state: StepState; num: number }) {
  if (state === 'success') {
    return (
      <div className="ars-icon ars-icon-success">
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="3,9 7.5,13.5 15,4" />
        </svg>
      </div>
    )
  }
  if (state === 'blocked') {
    return (
      <div className="ars-icon ars-icon-blocked">
        <svg width="16" height="16" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round">
          <line x1="4" y1="4" x2="14" y2="14" />
          <line x1="14" y1="4" x2="4" y2="14" />
        </svg>
      </div>
    )
  }
  if (state === 'skipped') {
    return (
      <div className="ars-icon ars-icon-skipped">
        <span className="ars-icon-dash">—</span>
      </div>
    )
  }
  if (state === 'active') {
    return (
      <div className="ars-icon ars-icon-active">
        <div className="ars-spinner" />
      </div>
    )
  }
  return (
    <div className="ars-icon ars-icon-upcoming">
      <span className="ars-icon-num">{num}</span>
    </div>
  )
}

export default function AIReasoningStepper({ steps }: AIReasoningStepperProps) {
  const stepMap = new Map(steps.map((s) => [s.id, s]))

  return (
    <div className="ars-root">
      <div className="ars-header">
        <div className="ars-title">How CORAL thinks</div>
        <div className="ars-subtitle">Each step happens before the robot moves</div>
      </div>
      <div className="ars-list">
        {STEP_ORDER.map((id, idx) => {
          const step = stepMap.get(id)
          const state: StepState = step?.state ?? 'upcoming'
          const expanded = state === 'active' || state === 'blocked'
          return (
            <div key={id} className={`ars-step ars-step-${state}`}>
              <div className="ars-step-header">
                <StepIcon state={state} num={idx + 1} />
                <div className="ars-step-meta">
                  <div className={`ars-step-label ars-step-label-${state}`}>{step?.label ?? labelFor(id)}</div>
                  {!expanded && step?.detail && (
                    <div className="ars-step-summary">{summarize(step.detail)}</div>
                  )}
                </div>
              </div>
              {expanded && step?.detail && (
                <div className="ars-step-detail">
                  <div className={`ars-step-detail-inner ars-step-detail-${state}`}>
                    {step.detail}
                    {step.action && (
                      <div className="ars-step-btns">
                        <button className="ars-step-btn-primary" onClick={step.action.onClick}>
                          {step.action.label}
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function labelFor(id: StepId): string {
  switch (id) {
    case 'command': return 'Your command'
    case 'understanding': return 'Understanding'
    case 'safety': return 'Safety check'
    case 'clarification': return 'Clarification'
    case 'execute': return 'Execute'
  }
}

function summarize(detail: string): string {
  const max = 48
  if (detail.length <= max) return detail
  return detail.slice(0, max).trim() + '…'
}
