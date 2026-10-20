import { SimPanel, AgentBubble } from '../parts'
import { ROBOT_NAME, type State, type Action } from '../state'

export function SimPlaygroundScreen({
  s,
  dispatch,
  cameraUrl,
  onNext,
  runBlockMove,
}: {
  s: State
  dispatch: React.Dispatch<Action>
  cameraUrl: string
  onNext: () => void
  runBlockMove: (part: string, dir: string) => Promise<void>
}) {
  const partOptions = ['Shoulder', 'Elbow', 'Wrist', 'Hip']
  const dirOptions = ['Raise', 'Lower', 'Extend', 'Bend']
  const bothSet = !!s.blockPart && !!s.blockDir
  const moveText = bothSet ? `${s.blockDir} ${s.blockPart}` : ''

  return (
    <>
      <div className="tut-colheader">
        <div className="tut-colheader-left">
          <div className="tut-logo-box">
            <div className="tut-logo-diamond" />
          </div>
          <span className="tut-badge tut-badge-explore">EXPLORE</span>
          <div className="tut-colheader-title">Simulator Playground</div>
        </div>
        <button className="tut-skip-btn" onClick={onNext}>
          Skip →
        </button>
      </div>

      <div className="tut-twocol">
        <SimPanel cameraUrl={cameraUrl} />
        <div className="tut-right">
          <div className="tut-right-scroll">
            <AgentBubble>
              This is a simulator — it moves just like the real {ROBOT_NAME} would. Try clicking a body part and dragging the ring to rotate it. That's a joint!
            </AgentBubble>

            <div className="tut-intent-tip">
              <span className="tut-intent-tip-dot" />
              Tip: green ring = safe, yellow = near the limit, red = blocked.
            </div>

            <div className="tut-blocks-header">
              <div className="tut-blocks-title">Or build a move, block by block</div>
            </div>
            <div className="tut-blocks-body">
              {/* Block 1 */}
              <div className={`tut-block-row ${s.blockPart ? 'tut-block-row-done' : 'tut-block-row-active'}`}>
                <div className="tut-block-inner">
                  <div className={`tut-block-num ${s.blockPart ? 'tut-block-num-done' : 'tut-block-num-active'}`}>1</div>
                  <div style={{ flex: 1 }}>
                    <div className="tut-block-label tut-block-label-on">Pick a body part</div>
                    <div className="tut-block-req">Needs: which joint</div>
                  </div>
                  {s.blockPart && <div className="tut-block-value">{s.blockPart}</div>}
                </div>
                <div className="tut-chips">
                  {partOptions.map((o) => (
                    <button
                      key={o}
                      className={`tut-chip ${s.blockPart === o ? 'tut-chip-sel' : 'tut-chip-unsel'}`}
                      onClick={() => dispatch({ type: 'SET_BLOCK_PART', val: o })}
                    >
                      {o}
                    </button>
                  ))}
                </div>
              </div>

              {/* Block 2 */}
              <div
                className={`tut-block-row ${
                  !s.blockPart ? 'tut-block-row-waiting' : s.blockDir ? 'tut-block-row-done' : 'tut-block-row-active'
                }`}
              >
                <div className="tut-block-inner">
                  <div
                    className={`tut-block-num ${
                      !s.blockPart ? 'tut-block-num-waiting' : s.blockDir ? 'tut-block-num-done' : 'tut-block-num-active'
                    }`}
                  >
                    2
                  </div>
                  <div style={{ flex: 1 }}>
                    <div className={`tut-block-label ${s.blockPart ? 'tut-block-label-on' : 'tut-block-label-off'}`}>
                      Set a direction
                    </div>
                    <div className="tut-block-req">Needs: which way</div>
                  </div>
                  {s.blockDir && <div className="tut-block-value">{s.blockDir}</div>}
                </div>
                {s.blockPart && (
                  <div className="tut-chips">
                    {dirOptions.map((o) => (
                      <button
                        key={o}
                        className={`tut-chip ${s.blockDir === o ? 'tut-chip-sel' : 'tut-chip-unsel'}`}
                        onClick={() => dispatch({ type: 'SET_BLOCK_DIR', val: o })}
                      >
                        {o}
                      </button>
                    ))}
                  </div>
                )}
                {!s.blockPart && <div className="tut-waiting-text">Finish the block above first.</div>}
              </div>

              {/* Block 3 */}
              <div className={`tut-block-row ${!bothSet ? 'tut-block-row-waiting' : 'tut-block-row-active'}`}>
                <div className="tut-block-inner">
                  <div className={`tut-block-num ${bothSet ? 'tut-block-num-active' : 'tut-block-num-waiting'}`}>3</div>
                  <div style={{ flex: 1 }}>
                    <div className={`tut-block-label ${bothSet ? 'tut-block-label-on' : 'tut-block-label-off'}`}>
                      Confirm & simulate
                    </div>
                  </div>
                </div>
                {bothSet && !s.blockChecking && !s.blockConfirmed && (
                  <div className="tut-confirm-btns" style={{ marginTop: 13 }}>
                    <button
                      className="tut-btn-primary"
                      style={{ flex: 1 }}
                      onClick={() => runBlockMove(s.blockPart!, s.blockDir!)}
                    >
                      Execute motion
                    </button>
                  </div>
                )}
                {bothSet && s.blockChecking && (
                  <div className="tut-block-checking">
                    <div className="tut-checking-card">
                      <div className="tut-checking-spinner" />
                      <div className="tut-checking-text">Checking safety…</div>
                    </div>
                  </div>
                )}
                {bothSet && s.blockConfirmed && (
                  <>
                    <div className="tut-confirm-row" style={{ marginTop: 13 }}>
                      <div className="tut-confirm-check">✓</div>
                      <div className="tut-confirm-text">
                        <strong>{moveText}</strong> completed
                      </div>
                    </div>
                    <div className="tut-confirm-btns">
                      <button className="tut-btn-ghost" onClick={() => dispatch({ type: 'BLOCK_RESET' })}>
                        Another
                      </button>
                    </div>
                  </>
                )}
                {!bothSet && <div className="tut-waiting-text">Finish the blocks above first.</div>}
              </div>
            </div>

            <button className="tut-next-btn" onClick={onNext}>
              I got it! Next →
            </button>
          </div>
        </div>
      </div>
    </>
  )
}
