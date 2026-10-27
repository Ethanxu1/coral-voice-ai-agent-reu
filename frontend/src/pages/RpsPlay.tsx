import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { LiveStream } from '../components/LiveStream'
import RobotViewer from '../components/RobotViewer'
import { usePoseWebSocket } from '../hooks/usePoseWebSocket'
import { resetPose } from '../api/robot'
import { stopSubjectSelection } from '../api/vision'
import { killSpeech, speak } from '../audio/speech'
import GestureFigure from '../rps/GestureFigure'
import SkeletonView, { followReadiness } from '../rps/SkeletonView'
import RpsBar from '../rps/RpsBar'
import RpsTopbar, { RPS_PATH } from '../rps/RpsTopbar'
import { gestureScores } from '../rps/classify'
import { customGestureSet } from '../rps/customMoves'
import { STANDARD_SET, type GestureSet } from '../rps/gestureSet'
import { poseRobot, resetRobot } from '../rps/robotPose'
import { BEATS, GESTURES, ROBOT_REST_PULSES, WINS_BECAUSE, type GestureId } from '../rps/gestures'
import './RefinedDemo.css'
import './RockPaperScissors.css'
import './RpsPlay.css'
import { sleep } from '../utils/sleep'

type Outcome = 'win' | 'lose' | 'draw'
type Phase = 'ready' | 'position' | 'countdown' | 'nopose' | 'captured' | 'result' | 'final'

interface RoundResult {
  child: GestureId
  robot: GestureId
  outcome: Outcome
  /** Best similarity (0-1) of the child's pose to the move they made, during the capture window. */
  similarity: number
  /** Time from "Shoot!" until the camera first saw that move, in ms. Kept for data logging later. */
  reactionMs: number
}

const ROUNDS = 3
const COUNT_STEPS = ['3', '2', '1', 'Shoot']
const STEP_MS = 900
/**
 * A move counts once its similarity reaches this. Lower than DETECTION.minSimilarity
 * (used by Learn), since it's a game: a roughly right pose should be enough.
 */
const MATCH = 0.6
/** After "Shoot!", the move seen most often in this window is the child's move… */
const CAPTURE_MS = 600
const SAMPLE_EVERY_MS = 50
/** …as long as it was seen in at least this share of the samples. */
const MIN_VOTE_SHARE = 1 / 3
const NOPOSE_MS = 1800
/** "Got it" shows for at least this long, and until CORAL's arms have arrived. */
const CAPTURED_MS = 1300
/** The round result moves on by itself after this, or sooner with the Next button. */
const RESULT_MS = 4000
/** Before the first round: give the child time to step back, then wait until both arms are in view this long. */
const POSITION_MIN_MS = 2000
const POSITION_STEADY_MS = 1000

function judge(child: GestureId, robot: GestureId): Outcome {
  if (child === robot) return 'draw'
  return BEATS[child] === robot ? 'win' : 'lose'
}

const ROUND_TEXT: Record<Outcome, string> = {
  win: 'You win this round',
  lose: 'CORAL wins this round',
  draw: "It's a draw",
}

/** What CORAL says aloud: in its own voice, and kind when it wins. */
const SPOKEN_ROUND_TEXT: Record<Outcome, string> = {
  win: 'You win this round. Nice one.',
  lose: 'I win this round. Good try.',
  draw: "We picked the same. It's a draw.",
}

/** Red (0) → yellow (0.5) → green (1). */
const scoreColor = (s: number) => `hsl(${Math.round(s * 120)} ${s > 0.6 ? 55 : 78}% ${s > 0.6 ? 40 : 50}%)`

function say(text: string) {
  killSpeech()
    .then(() => speak({ text }))
    .catch(() => {})
}

/** Play screen: three rounds against CORAL. CORAL picks its move only after it has seen the child's. */
export default function RpsPlay() {
  const [params] = useSearchParams()
  const wantsCustom = params.get('moves') === 'custom'
  const set = useMemo(() => (wantsCustom ? customGestureSet() : STANDARD_SET), [wantsCustom])

  if (!set) {
    return (
      <div className="rd-root">
        <RpsTopbar />
        <main className="rps-menu">
          <h1 className="rps-menu-title">No moves yet</h1>
          <p className="rps-menu-sub">Record your own rock, paper and scissors first.</p>
          <Link to={`${RPS_PATH}/custom`} className="rps-big-btn">
            Make your own moves
          </Link>
        </main>
      </div>
    )
  }
  return <Game set={set} />
}

function Game({ set }: { set: GestureSet }) {
  const { bodyLandmarks, trackingLost } = usePoseWebSocket()
  const body = trackingLost ? [] : bodyLandmarks

  const [phase, setPhase] = useState<Phase>('ready')
  const [round, setRound] = useState(1)
  const [count, setCount] = useState(COUNT_STEPS[0])
  const [youMove, setYouMove] = useState<GestureId | null>(null)
  const [results, setResults] = useState<RoundResult[]>([])
  const [hints, setHints] = useState(false)

  const scores = useMemo(() => gestureScores(body, set), [body, set])
  const detected = useMemo(() => {
    if (!scores) return null
    const top = GESTURES.reduce((a, g) => (scores[g.id] > scores[a] ? g.id : a), GESTURES[0].id)
    return scores[top] >= MATCH ? top : null
  }, [scores])
  const readiness = followReadiness(body)

  // The game loop samples the camera outside React's render cycle.
  const detectedRef = useRef(detected)
  detectedRef.current = detected
  const scoresRef = useRef(scores)
  scoresRef.current = scores
  const readyRef = useRef(readiness.ok)
  readyRef.current = readiness.ok

  const runIdRef = useRef(0)
  /** Ends the current result wait early (the Next button). */
  const nextRef = useRef<(() => void) | null>(null)

  useEffect(() => {
    stopSubjectSelection()
    resetRobot().catch(() => {})
    return () => {
      runIdRef.current++
      killSpeech()
      resetPose().catch(() => {})
    }
  }, [])

  const waitForNext = (ms: number) =>
    new Promise<void>((resolve) => {
      const done = () => {
        clearTimeout(timer)
        nextRef.current = null
        resolve()
      }
      const timer = setTimeout(done, ms)
      nextRef.current = done
    })

  /**
   * Countdown and capture until the camera sees a move. Null if cancelled.
   * `onShoot` runs at every "Shoot", and `onMiss` when no move was seen and the countdown restarts.
   */
  const captureMove = useCallback(
    async (
      cancelled: () => boolean,
      onShoot: () => void,
      onMiss: () => void,
    ): Promise<Pick<RoundResult, 'child' | 'similarity' | 'reactionMs'> | null> => {
      for (;;) {
        for (const step of COUNT_STEPS) {
          if (cancelled()) return null
          setCount(step)
          setPhase('countdown')
          if (step !== 'Shoot') await sleep(STEP_MS)
        }
        onShoot()

        // "Shoot!" stays up while the child settles, then the camera votes over a short window.
        const votes: Record<GestureId, number> = { rock: 0, paper: 0, scissors: 0 }
        const best: Record<GestureId, number> = { rock: 0, paper: 0, scissors: 0 }
        const firstSeen: Partial<Record<GestureId, number>> = {}
        const shoot = Date.now()
        let samples = 0
        while (Date.now() - shoot < STEP_MS + CAPTURE_MS) {
          if (cancelled()) return null
          const seen = detectedRef.current
          if (seen) firstSeen[seen] ??= Date.now() - shoot
          if (Date.now() - shoot >= STEP_MS) {
            samples++
            if (seen) votes[seen]++
            const s = scoresRef.current
            if (s) for (const g of GESTURES) best[g.id] = Math.max(best[g.id], s[g.id])
          }
          await sleep(SAMPLE_EVERY_MS)
        }
        if (cancelled()) return null

        const top = (Object.keys(votes) as GestureId[]).reduce((a, b) => (votes[b] > votes[a] ? b : a))
        if (votes[top] > 0 && votes[top] >= samples * MIN_VOTE_SHARE) {
          return { child: top, similarity: best[top], reactionMs: firstSeen[top] ?? 0 }
        }
        setPhase('nopose')
        onMiss()
        say("I couldn't see a move. Let's try again.")
        await sleep(NOPOSE_MS)
      }
    },
    [],
  )

  const playRound = useCallback(
    async (cancelled: () => boolean): Promise<RoundResult | null> => {
      await resetRobot().catch((e) => console.warn('robot reset failed', e))
      setYouMove(null)

      // CORAL throws at "Shoot", at the same time as the child: it picks at random
      // and starts moving while the camera is still reading the child's move.
      // Moves are chained so a restart's reset never cuts into a move still easing in.
      let robot = set.gestures[0].id
      let moving: Promise<unknown> = Promise.resolve()
      const child = await captureMove(
        cancelled,
        () => {
          robot = set.gestures[Math.floor(Math.random() * set.gestures.length)].id
          const pulses = set.byId[robot].robotPulses
          // It always starts from the stand pose (reset at the start of the round, or after a miss).
          moving = moving
            .then(() => poseRobot(pulses, undefined, ROBOT_REST_PULSES))
            .catch((e) => console.warn('robot move failed', e))
        },
        () => {
          moving = moving.then(() => resetRobot()).catch((e) => console.warn('robot reset failed', e))
        },
      )
      if (!child) return null
      setYouMove(child.child)
      setPhase('captured')
      await Promise.all([moving, sleep(CAPTURED_MS)])
      if (cancelled()) return null

      return { ...child, robot, outcome: judge(child.child, robot) }
    },
    [set, captureMove],
  )

  const playMatch = useCallback(async () => {
    const run = ++runIdRef.current
    const cancelled = () => run !== runIdRef.current
    setResults([])
    setRound(1)

    // Start was pressed at the computer: wait for the child to step back into view.
    setPhase('position')
    say('Step back so I can see both of your arms.')
    const begin = Date.now()
    let steadySince: number | null = null
    for (;;) {
      if (cancelled()) return
      const now = Date.now()
      steadySince = readyRef.current ? steadySince ?? now : null
      if (now - begin >= POSITION_MIN_MS && steadySince !== null && now - steadySince >= POSITION_STEADY_MS) break
      await sleep(100)
    }

    const done: RoundResult[] = []
    while (done.length < ROUNDS) {
      if (cancelled()) return
      setRound(done.length + 1)
      const r = await playRound(cancelled)
      if (!r || cancelled()) return
      done.push(r)
      setResults([...done])
      setPhase('result')
      say(`You chose ${set.byId[r.child].label}. I chose ${set.byId[r.robot].label}. ${SPOKEN_ROUND_TEXT[r.outcome]}`)
      await waitForNext(RESULT_MS)
    }
    if (cancelled()) return

    setPhase('final')
    const you = done.filter((r) => r.outcome === 'win').length
    const coral = done.filter((r) => r.outcome === 'lose').length
    say(you > coral ? 'You win. Great game.' : coral > you ? 'I won this time. That was fun. Want to play again?' : "It's a tie. Let's play again.")
  }, [set, playRound])

  // Space or Enter presses whatever the big button on screen is.
  const phaseRef = useRef(phase)
  phaseRef.current = phase
  const hintsRef = useRef(hints)
  hintsRef.current = hints
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== ' ' && e.key !== 'Enter') return
      e.preventDefault()
      if (hintsRef.current) setHints(false)
      else if (phaseRef.current === 'ready' || phaseRef.current === 'final') playMatch()
      else if (phaseRef.current === 'result') nextRef.current?.()
    }
    addEventListener('keydown', onKey)
    return () => removeEventListener('keydown', onKey)
  }, [playMatch])

  const you = results.filter((r) => r.outcome === 'win').length
  const coral = results.filter((r) => r.outcome === 'lose').length
  const last = phase === 'result' ? results[results.length - 1] : null
  const visible = body.length > 0
  const overCoral = phase === 'position' || phase === 'countdown' || phase === 'nopose' || phase === 'captured'
  // From "Shoot" CORAL is moving, so its panel is uncovered and the card shrinks to a strip at the top.
  const showCoral = phase === 'captured' || (phase === 'countdown' && count === 'Shoot')

  return (
    <div className="rpsp">
      <RpsBar
        actions={
          <button className="btn hints" onClick={() => setHints(true)}>
            <span className="ico">?</span>RPS Hints
          </button>
        }
      >
        <div className="round">
          <div className="round-title">
            Round {Math.min(round, ROUNDS)} of {ROUNDS}
            {set.kind === 'custom' && <span className="own">Your moves</span>}
          </div>
          <div className="pips">
            {Array.from({ length: ROUNDS }, (_, i) => (
              <span
                key={i}
                className={`pip ${i < results.length ? results[i].outcome : i === results.length && phase !== 'ready' && phase !== 'final' ? 'now' : ''}`}
              />
            ))}
          </div>
        </div>
        <div className="score">
          <span className="who">You</span>
          <span key={`y${you}`} className={`n you ${you > 0 ? 'bump' : ''}`}>{you}</span>
          <span className="colon">:</span>
          <span key={`c${coral}`} className={`n coral ${coral > 0 ? 'bump' : ''}`}>{coral}</span>
          <span className="who">CORAL</span>
        </div>
      </RpsBar>

      <main className="main">
        <section className={`panel sim ${last?.outcome === 'lose' ? 'winner' : ''}`}>
          <div className="rd-sim-grid" />
          <RobotViewer embedded />
          <div className="rd-sim-vignette" />
          <div className="panel-head">
            <span className="tag">
              <i />
              CORAL · Simulation
            </span>
          </div>
          {last && (
            <div className={`played ${last.outcome === 'lose' ? 'won' : ''}`}>
              <span className="em">{set.byId[last.robot].emoji}</span>CORAL played {set.byId[last.robot].label}
              {last.outcome === 'lose' && <span className="crown">👑</span>}
            </div>
          )}
          {overCoral && (
            <div className={`count-wrap ${showCoral ? 'top' : ''}`}>
              <CountCard phase={phase} count={count} round={round} ready={readiness.ok} move={youMove} set={set} />
            </div>
          )}
        </section>

        <section className={`panel me ${overCoral ? 'raised' : ''} ${last?.outcome === 'win' ? 'winner' : ''}`}>
          <div className="hint-col">
            <div className="hint-col-title">
              Your move<small>green = CORAL sees it</small>
            </div>
            {set.gestures.map((g) => {
              const s = scores ? scores[g.id] : 0
              return (
                <div key={g.id} className={`hint ${detected === g.id ? 'match' : ''}`}>
                  <div className="fig">
                    <GestureFigure gesture={g} />
                  </div>
                  <div className="name">
                    {g.label}
                    <span className="pct" style={{ color: scores ? scoreColor(s) : 'var(--faint)' }}>
                      {scores ? `${Math.round(s * 100)}%` : '–'}
                    </span>
                  </div>
                  <div className="tip">{g.tip}</div>
                  <div className="meter">
                    <div className="fill" style={{ width: `${Math.max(scores ? 3 : 0, s * 100)}%`, background: scoreColor(s) }} />
                    <div className="goal" style={{ left: `${MATCH * 100}%` }} />
                  </div>
                </div>
              )
            })}
            <div className="legend">
              0%<span className="grad" />100%
            </div>
          </div>
          <div className="skel">
            <div className="panel-head" style={{ left: 16 }}>
              <span className={`tag soft ${readiness.ok ? 'ok' : 'warn'}`}>
                <i />
                {readiness.ok ? 'I can see your head and arms' : visible ? readiness.message : 'Step in front of the camera'}
              </span>
            </div>
            {visible ? (
              <SkeletonView landmarks={body} />
            ) : (
              <div className="skel-empty">
                <div>
                  <b>I can't see you yet</b>Stand where the camera can see your head and arms
                </div>
              </div>
            )}
            {last && (
              <div className={`played ${last.outcome === 'win' ? 'won' : ''}`}>
                <span className="em">{set.byId[last.child].emoji}</span>You played {set.byId[last.child].label}
                {last.outcome === 'win' && <span className="crown">👑</span>}
              </div>
            )}
            <div className="cam">
              <LiveStream badge={false} />
              <span className="live">
                <i />
                LIVE
              </span>
            </div>
          </div>
        </section>

        {last && (
          <div className={`result ${last.outcome}`}>
            <div className="kicker">
              Round {results.length} of {ROUNDS}
            </div>
            <div className="vs">
              <div className={`side ${last.outcome === 'win' ? 'won' : ''}`}>
                <small>You</small>
                <span className="em">{set.byId[last.child].emoji}</span>
                <b>{set.byId[last.child].label}</b>
              </div>
              <span className="x">vs</span>
              <div className={`side ${last.outcome === 'lose' ? 'won' : ''}`}>
                <small>CORAL</small>
                <span className="em">{set.byId[last.robot].emoji}</span>
                <b>{set.byId[last.robot].label}</b>
              </div>
            </div>
            <h1>{ROUND_TEXT[last.outcome]}</h1>
            <div className="why">
              {last.outcome === 'draw'
                ? 'You both picked the same move.'
                : `${WINS_BECAUSE[last.outcome === 'win' ? last.child : last.robot]}`}
            </div>
            <button className="next" onClick={() => nextRef.current?.()}>
              {results.length >= ROUNDS ? 'See who won →' : 'Next round →'}
              <span key={results.length} className="auto" style={{ '--wait': `${RESULT_MS}ms` } as React.CSSProperties} />
            </button>
          </div>
        )}
      </main>

      {overCoral && !showCoral && <div className="backdrop" />}

      {phase === 'ready' && !hints && (
        <div className="backdrop">
          <div className="modal">
            <div className="kicker">Rock · Paper · Scissors</div>
            <h1>Ready to play CORAL?</h1>
            <div className="sub">
              Best of {ROUNDS} rounds. When the countdown ends, hold your move until CORAL says “Got it”.
            </div>
            <MoveTiles set={set} />
            <div className={`ready-check ${readiness.ok ? '' : 'warn'}`}>
              <span className="dot">{readiness.ok ? '✓' : '!'}</span>
              {readiness.ok ? 'CORAL can see you. You’re ready.' : 'Step back so CORAL can see your head and arms'}
            </div>
            <button className="start" onClick={playMatch}>
              Start
            </button>
            <div className="keyhint">Press Space or Enter</div>
          </div>
        </div>
      )}

      {phase === 'final' && !hints && <FinalCard results={results} set={set} onAgain={playMatch} />}

      {hints && <HintsModal set={set} onClose={() => setHints(false)} />}
    </div>
  )
}

function MoveTiles({ set }: { set: GestureSet }) {
  return (
    <div className="tiles">
      {set.gestures.map((g) => (
        <div key={g.id} className="tile">
          <span className="em">{g.emoji}</span>
          <div className="fig">
            <GestureFigure gesture={g} />
          </div>
          <div className="name">{g.label}</div>
          <div className="tip">{g.tip}</div>
        </div>
      ))}
    </div>
  )
}

/** The card over CORAL's panel from Start until the child's move is captured. */
function CountCard({
  phase,
  count,
  round,
  ready,
  move,
  set,
}: {
  phase: Phase
  count: string
  round: number
  ready: boolean
  move: GestureId | null
  set: GestureSet
}) {
  if (phase === 'position') {
    return (
      <div className="modal count-card">
        <div className="kicker">Get in position</div>
        <h1>{ready ? 'Great, hold on…' : 'Step back'}</h1>
        <div className="sub">{ready ? 'The countdown starts in a moment.' : 'So CORAL can see your head and both arms.'}</div>
        <div className="pointer">Watch for the green tag →</div>
      </div>
    )
  }
  if (phase === 'nopose') {
    return (
      <div className="modal count-card amber">
        <div className="kicker">Hmm…</div>
        <h1>I couldn't see a move</h1>
        <div className="sub">Make Rock, Paper or Scissors so one bar goes green.</div>
        <div className="again">Starting again…</div>
      </div>
    )
  }
  if (phase === 'captured' && move) {
    const g = set.byId[move]
    return (
      <div className="modal count-card compact green">
        <span className="kicker">Got it</span>
        <span className="em">{g.emoji}</span>
        <span className="word">{g.label}</span>
      </div>
    )
  }
  const word = count === 'Shoot'
  if (word) {
    return (
      <div className="modal count-card compact">
        <span className="kicker">Round {round}</span>
        <span className="word">Shoot</span>
        <span className="sub">Hold it still…</span>
      </div>
    )
  }
  return (
    <div className="modal count-card">
      <div className="kicker">Round {round} · Make your move</div>
      <div key={count} className="ring" style={{ '--step': `${STEP_MS}ms` } as React.CSSProperties}>
        <svg viewBox="0 0 230 230">
          <circle className="track" cx="115" cy="115" r="100" />
          <circle className="prog" cx="115" cy="115" r="100" />
        </svg>
        <span className={`num ${word ? 'word' : ''}`}>{count}</span>
      </div>
      <div className="sub">{word ? 'Hold it still…' : 'Get your arms ready'}</div>
      <div className="pointer">Watch your bars turn green →</div>
    </div>
  )
}

function HintsModal({ set, onClose }: { set: GestureSet; onClose: () => void }) {
  return (
    <div className="backdrop" style={{ zIndex: 70 }}>
      <div className="modal hint-modal">
        <div className="kicker">RPS Hints</div>
        <h1>How to make each move</h1>
        <div className="tiles">
          {set.gestures.map((g) => {
            const beaten = set.byId[BEATS[g.id]]
            return (
              <div key={g.id} className="tile">
                <span className="em">{g.emoji}</span>
                <div className="fig">
                  <GestureFigure gesture={g} />
                </div>
                <div className="name">{g.label}</div>
                {g.steps.length > 0 ? (
                  <ol>
                    {g.steps.map((s) => (
                      <li key={s}>{s}</li>
                    ))}
                  </ol>
                ) : (
                  <div className="tip">{g.tagline}</div>
                )}
                <div className="beats">
                  Beats {beaten.label} {beaten.emoji}
                </div>
              </div>
            )
          })}
        </div>
        <div className="cycle">
          <span>✊</span>smashes<span>✌️</span>cut<span>✋</span>wraps<span>✊</span>
        </div>
        <button className="cta" onClick={onClose}>
          Got it
        </button>
      </div>
    </div>
  )
}

function FinalCard({ results, set, onAgain }: { results: RoundResult[]; set: GestureSet; onAgain: () => void }) {
  const you = results.filter((r) => r.outcome === 'win').length
  const coral = results.filter((r) => r.outcome === 'lose').length
  const verdict = you > coral ? 'You beat CORAL 🎉' : you < coral ? 'CORAL wins this time' : "It's a tie"
  const confetti = useMemo(
    () =>
      Array.from({ length: 70 }, (_, i) => ({
        left: `${Math.random() * 100}%`,
        background: ['#FF6B4A', '#17BEBB', '#FFD54F', '#2E9E5B', '#7B4BB9'][i % 5],
        animationDuration: `${2 + Math.random() * 2}s`,
        animationDelay: `${Math.random() * 0.8}s`,
      })),
    [],
  )
  return (
    <>
      <div className="backdrop">
        <div className="modal final">
          <div className="kicker">Match over</div>
          <h1>{verdict}</h1>
          <div className="big-score">
            <div>
              <div className="n you">{you}</div>
              <small>You</small>
            </div>
            <span className="dash">–</span>
            <div>
              <div className="n coral">{coral}</div>
              <small>CORAL</small>
            </div>
          </div>
          <div className="history">
            {results.map((r, i) => (
              <div key={i} className="row">
                <span className="r">Round {i + 1}</span>
                <span className="m">
                  {set.byId[r.child].emoji} {set.byId[r.child].label}
                </span>
                <span className="vsx">vs</span>
                <span className="m right">
                  {set.byId[r.robot].label} {set.byId[r.robot].emoji}
                </span>
                <span className={`o ${r.outcome}`}>{{ win: 'You', lose: 'CORAL', draw: 'Draw' }[r.outcome]}</span>
              </div>
            ))}
          </div>
          <div className="actions">
            <Link to={`${RPS_PATH}/learn`} className="ghost">
              Learn the moves
            </Link>
            <button className="next" style={{ marginTop: 0 }} onClick={onAgain}>
              Play again
            </button>
          </div>
        </div>
      </div>
      {you > coral && (
        <div className="confetti">
          {confetti.map((style, i) => (
            <i key={i} style={style} />
          ))}
        </div>
      )}
    </>
  )
}
