import { useState } from 'react'
import { Link } from 'react-router-dom'
import './TestUI.css'

import Page1_Welcome from './Page1_Welcome'
import Page2_ClassifyInstructions from './Page2_ClassifyInstructions'
import Page3_ClassifyCountdown from './Page3_ClassifyCountdown'
import Page4_ClassifyResults from './Page4_ClassifyResults'
import Page5_RecordInstructions from './Page5_RecordInstructions'
import Page6_RecordMic from './Page6_RecordMic'
import Page7_Name from './Page7_Name'
import Page8_Outro from './Page8_Outro'

const PAGES = [
  { label: 'Welcome',               component: Page1_Welcome },
  { label: 'Classify: Instructions', component: Page2_ClassifyInstructions },
  { label: 'Classify: Countdown',   component: Page3_ClassifyCountdown },
  { label: 'Classify: Results',     component: Page4_ClassifyResults },
  { label: 'Record: Instructions',  component: Page5_RecordInstructions },
  { label: 'Record: Listening',     component: Page6_RecordMic },
  { label: 'Naming',                component: Page7_Name },
  { label: 'Outro',                 component: Page8_Outro },
]

export default function TestUIRouter() {
  const [pageIndex, setPageIndex] = useState(0)
  const [key, setKey] = useState(0) // remount page component to retrigger animations

  function go(i: number) {
    setPageIndex(i)
    setKey((k) => k + 1)
  }

  const Page = PAGES[pageIndex].component

  return (
    <div className="tui-root">
      {/* ── Nav bar ── */}
      <nav className="tui-nav">
        <div className="tui-nav-left">
          <Link to="/">
            <button className="tui-btn tui-btn-home">← Back</button>
          </Link>
          <span style={{ fontWeight: 700, fontSize: 13, opacity: 0.6 }}>
            {pageIndex + 1}/{PAGES.length}
          </span>
        </div>

        <div className="tui-nav-center">
          <div className="tui-nav-title">{PAGES[pageIndex].label}</div>
          <div className="tui-dots">
            {PAGES.map((_, i) => (
              <button
                key={i}
                className={`tui-dot ${i === pageIndex ? 'active' : ''}`}
                onClick={() => go(i)}
                title={PAGES[i].label}
              />
            ))}
          </div>
        </div>

        <div className="tui-nav-right">
          <button
            className="tui-btn"
            disabled={pageIndex === 0}
            onClick={() => go(pageIndex - 1)}
          >
            ← Prev
          </button>
          <button
            className="tui-btn"
            disabled={pageIndex === PAGES.length - 1}
            onClick={() => go(pageIndex + 1)}
          >
            Next →
          </button>
        </div>
      </nav>

      {/* ── Page content ── */}
      <Page key={key} />
    </div>
  )
}
