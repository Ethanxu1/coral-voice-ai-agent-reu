import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import RobotViewer from '../components/RobotViewer'
import { usePoseWebSocket } from '../hooks/usePoseWebSocket'
import { resetPose } from '../api/robot'
import { stopSubjectSelection } from '../api/vision'
import { killSpeech, speak } from '../audio/speech'
import { bodyFit, offEdges, type Fit } from '../rps/bodyFit'
import CoralEye from '../rps/CoralEye'
import { coralMoves } from '../rps/coralMoves'
import CornerMenu from '../rps/CornerMenu'
import PoseArt, { MOVE_COLOR } from '../rps/PoseArt'
import RpsTopbar, { RPS_PATH } from '../rps/RpsTopbar'
import { gestureScores } from '../rps/classify'
import { customGestureSet } from '../rps/customMoves'
import { STANDARD_SET, type GestureSet } from '../rps/gestureSet'
import { poseRobot, resetRobot } from '../rps/robotPose'
import { sfx } from '../rps/sounds'
import { useSmoothedScores } from '../rps/useSmoothedScores'
import { BEATS, GESTURES, ROBOT_REST_PULSES, WINS_BECAUSE, type GestureId } from '../rps/gestures'
import './RefinedDemo.css'
import './RockPaperScissors.css'
import './RpsGame.css'
import { sleep } from '../utils/sleep'

type Outcome = 'win' | 'lose' | 'draw'
type Phase = 'ready' | 'position' | 'countdown' | 'nopose' | 'captured' | 'result' | 'final'

interface RoundResult {
  child: GestureId
  robot: GestureId
  outcome: Outcome
  /** Best similarity (0-1) of the child's pose to the move they made, during the capture window. */
  similarity: number
  /** Time from "Shoot" until the camera first saw that move, in ms. Kept for data logging later. */
  reactionMs: number
}

const ROUNDS = 3
const COUNT_STEPS = ['Rock', 'Paper', 'Scissors', 'Shoot']
const STEP_MS = 900
/**
 * CORAL starts its move at this step. A full arm swing takes about 1.7 s, so
 * starting at Shoot left the child waiting with nothing happening.
 */
const THROW_AT = 'Paper'
/**
 * A move counts once its similarity reaches this. Lower than DETECTION.minSimilarity
 * (used by Learn), since it's a game: a roughly right pose should be enough.
 */
const MATCH = 0.6
/** After "Shoot", the move seen most often in this window is the child's move… */
const CAPTURE_MS = 600
const SAMPLE_EVERY_MS = 50
/** …as long as it was seen in at least this share of the samples. */
const MIN_VOTE_SHARE = 1 / 3
const NOPOSE_MS = 1800
/** "Got it" shows for at least this long, and until CORAL's arms have arrived. */
const CAPTURED_MS = 1300
/** CORAL holds its move this long in the reveal before it reacts. */
const REACT_AFTER_MS = 1500
/** Before the first round: give the child time to get in place, then wait until their head and shoulders are in view this long. */
const POSITION_MIN_MS = 2000
const POSITION_STEADY_MS = 1000
/** CORAL's positioning tips are spoken no more often than this. */
const TIP_EVERY_MS = 2500

function judge(child: GestureId, robot: GestureId): Outcome {
  if (child === robot) return 'draw'
  return BEATS[child] === robot ? 'win' : 'lose'
}

/** What CORAL says after a round, in its own voice, and kind when it wins. */
const ROUND_LINE: Record<Outcome, string> = {
  win: 'You got me!',
  lose: 'I win this one!',
  draw: 'Ooh, same move!',
}

/** CORAL's tips while the child finds their spot. */
const FIT_LINE: Record<Fit, string> = {
  away: 'Come stand where I can see you!',
  far: 'Come a little closer!',
  close: 'Step back!',
  side: 'Scoot to the middle!',
  fit: 'Perfect!',
}

/** After a miss. If a hand was out of the picture, the child is too close for that move. */
const MISS_LINE = 'Oops, I missed that. Again!'
const MISS_HANDS_LINE = 'Step back a little so I can see your hands!'

const finalLine = (you: number, coral: number) =>
  you > coral ? 'You beat me! Wow!' : coral > you ? 'I won! Rematch?' : 'Ooh, we tied! Rematch?'

/**
 * Speak a line in CORAL's voice. Exclamation marks are shown on screen but not
 * spoken: they made the voice sound harsh.
 */
function say(text: string) {
  killSpeech()
    .then(() => speak({ text: text.replace(/!/g, '.').replace(/…/g, '...') }))
    .catch(() => {})
}

/** Play screen: three rounds against CORAL. CORAL picks its move at random, before it has seen the child's. */
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
  const [help, setHelp] = useState(false)

  const scores = useMemo(() => gestureScores(body, set), [body, set])
  const detected = useMemo(() => {
    if (!scores) return null
    const top = GESTURES.reduce((a, g) => (scores[g.id] > scores[a] ? g.id : a), GESTURES[0].id)
    return scores[top] >= MATCH ? top : null
  }, [scores])
  // What lights up for the child: smoothed, so camera noise doesn't make it blink.
  const { shown, matched } = useSmoothedScores(scores, MATCH)
  const fit = bodyFit(body)

  // The game loop samples the camera outside React's render cycle.
  const detectedRef = useRef(detected)
  detectedRef.current = detected
  const scoresRef = useRef(scores)
  scoresRef.current = scores
  const fitRef = useRef(fit)
  fitRef.current = fit
  const handsOutRef = useRef(false)
  handsOutRef.current = offEdges(body).length > 0
  const [missLine, setMissLine] = useState(MISS_LINE)

  const runIdRef = useRef(0)
  /** Ends the wait on the round result (the Next button). */
  const nextRef = useRef<(() => void) | null>(null)

  useEffect(() => {
    stopSubjectSelection()
    // CORAL waves hello until the game starts.
    const run = runIdRef.current
    resetRobot()
      .then(() => {
        say("Hi! I'm CORAL. Want to play Rock, Paper, Scissors with me?")
        return coralMoves.wave(() => run !== runIdRef.current)
      })
      .catch(() => {})
    return () => {
      runIdRef.current++
      killSpeech()
      resetPose().catch(() => {})
    }
  }, [])

  // A pop whenever CORAL starts seeing a move.
  useEffect(() => {
    if (matched && phase !== 'captured' && phase !== 'result' && phase !== 'final') sfx.seen()
  }, [matched])

  /** The result stays up until the Next button (or Space/Enter) is pressed: the game never moves on by itself. */
  const waitForNext = () =>
    new Promise<void>((resolve) => {
      nextRef.current = () => {
        nextRef.current = null
        resolve()
      }
    })

  /**
   * Countdown and capture until the camera sees a move. Null if cancelled.
   * `onThrow` runs at every THROW_AT step, and `onMiss` when no move was seen and the countdown restarts.
   */
  const captureMove = useCallback(
    async (
      cancelled: () => boolean,
      onThrow: () => void,
      onMiss: () => void,
    ): Promise<Pick<RoundResult, 'child' | 'similarity' | 'reactionMs'> | null> => {
      for (;;) {
        for (const step of COUNT_STEPS) {
          if (cancelled()) return null
          setCount(step)
          setPhase('countdown')
          if (step === 'Shoot') sfx.shoot()
          else sfx.tick()
          if (step === THROW_AT) onThrow()
          if (step !== 'Shoot') await sleep(STEP_MS)
        }

        // "Shoot" stays up while the child settles, then the camera votes over a short window.
        const votes: Record<GestureId, number> = { rock: 0, paper: 0, scissors: 0 }
        const best: Record<GestureId, number> = { rock: 0, paper: 0, scissors: 0 }
        const firstSeen: Partial<Record<GestureId, number>> = {}
        const shoot = Date.now()
        let samples = 0
        let handsOut = false
        while (Date.now() - shoot < STEP_MS + CAPTURE_MS) {
          if (cancelled()) return null
          const seen = detectedRef.current
          if (seen) firstSeen[seen] ??= Date.now() - shoot
          if (Date.now() - shoot >= STEP_MS) {
            samples++
            handsOut ||= handsOutRef.current
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
        const line = handsOut ? MISS_HANDS_LINE : MISS_LINE
        setMissLine(line)
        setPhase('nopose')
        onMiss()
        sfx.miss()
        say(line)
        await sleep(NOPOSE_MS)
      }
    },
    [],
  )

  const playRound = useCallback(
    async (cancelled: () => boolean): Promise<RoundResult | null> => {
      await resetRobot().catch((e) => console.warn('robot reset failed', e))
      setYouMove(null)

      // CORAL picks at random and starts moving during the countdown (THROW_AT), so its
      // arms arrive about when the child shoots instead of seconds after.
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
      sfx.lock()
      say('Got it!')
      await Promise.all([moving, sleep(CAPTURED_MS)])
      if (cancelled()) return null

      return { ...child, robot, outcome: judge(child.child, robot) }
    },
    [set, captureMove],
  )

  /** Before the first round: CORAL coaches the child until their head and shoulders are in view. */
  const positionChild = useCallback(async (cancelled: () => boolean) => {
    setPhase('position')
    const begin = Date.now()
    let steadySince: number | null = null
    let lastTip: Fit | null = null
    let lastTipAt = 0
    for (;;) {
      if (cancelled()) return
      const now = Date.now()
      const f = fitRef.current
      if (f === 'fit' && lastTip !== 'fit') {
        sfx.fit()
        say(FIT_LINE.fit)
        lastTip = 'fit'
        lastTipAt = now
      } else if (f !== 'fit' && f !== lastTip && now - lastTipAt >= TIP_EVERY_MS) {
        say(FIT_LINE[f])
        lastTip = f
        lastTipAt = now
      }
      steadySince = f === 'fit' ? steadySince ?? now : null
      if (now - begin >= POSITION_MIN_MS && steadySince !== null && now - steadySince >= POSITION_STEADY_MS) return
      await sleep(100)
    }
  }, [])

  const playMatch = useCallback(async () => {
    const run = ++runIdRef.current
    const cancelled = () => run !== runIdRef.current
    setResults([])
    setRound(1)

    await positionChild(cancelled)

    const done: RoundResult[] = []
    while (done.length < ROUNDS) {
      if (cancelled()) return
      setRound(done.length + 1)
      const r = await playRound(cancelled)
      if (!r || cancelled()) return
      done.push(r)
      setResults([...done])
      setPhase('result')
      sfx[r.outcome === 'draw' ? 'tie' : r.outcome]()
      const why = r.outcome === 'draw' ? '' : `${WINS_BECAUSE[r.outcome === 'win' ? r.child : r.robot]}. `
      say(`You picked ${set.byId[r.child].label}. I picked ${set.byId[r.robot].label}. ${why}${ROUND_LINE[r.outcome]}`)
      const reacting = sleep(REACT_AFTER_MS).then(() =>
        coralMoves.react(r.outcome === 'lose' ? 'coral' : r.outcome === 'win' ? 'child' : 'draw', cancelled),
      )
      await waitForNext()
      // The next round's reset must not cut into a reaction still easing in.
      await reacting
    }
    if (cancelled()) return

    setPhase('final')
    const you = done.filter((r) => r.outcome === 'win').length
    const coral = done.filter((r) => r.outcome === 'lose').length
    sfx[you > coral ? 'win' : coral > you ? 'lose' : 'tie']()
    say(finalLine(you, coral))
    coralMoves.dance(cancelled)
  }, [set, playRound, positionChild])

  // Space or Enter presses whatever the big button on screen is (for the grown-up at the keyboard).
  const phaseRef = useRef(phase)
  phaseRef.current = phase
  const helpRef = useRef(help)
  helpRef.current = help
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== ' ' && e.key !== 'Enter') return
      e.preventDefault()
      if (helpRef.current) setHelp(false)
      else if (phaseRef.current === 'ready' || phaseRef.current === 'final') playMatch()
      else if (phaseRef.current === 'result') nextRef.current?.()
    }
    addEventListener('keydown', onKey)
    return () => removeEventListener('keydown', onKey)
  }, [playMatch])

  const you = results.filter((r) => r.outcome === 'win').length
  const coral = results.filter((r) => r.outcome === 'lose').length
  const last = phase === 'result' ? results[results.length - 1] : null
  const playing = phase === 'position' || phase === 'countdown' || phase === 'nopose' || phase === 'captured'
  const lit = phase === 'captured' ? youMove : matched

  // One message at a time, in CORAL's speech bubble.
  const bubble =
    phase === 'ready'
      ? "Hi! I'm CORAL. Wanna play?"
      : phase === 'position'
        ? FIT_LINE[fit]
        : phase === 'nopose'
          ? missLine
          : phase === 'captured'
            ? 'Got it!'
            : last
              ? ROUND_LINE[last.outcome]
              : phase === 'final'
                ? finalLine(you, coral)
                : null

  return (
    <div className={`rpsg phase-${phase}`}>
      <header className="top">
        {phase !== 'ready' && <Scoreboard results={results} round={round} you={you} coral={coral} />}
        <CornerMenu onHelp={() => setHelp(true)} />
      </header>

      <main className="stage-row">
        <section className={`coral-stage ${last?.outcome === 'lose' ? 'happy' : last?.outcome === 'win' ? 'sad' : ''}`}>
          <div className="robot">
            <div className="floor" />
            <RobotViewer embedded look="stage" />
          </div>
          {bubble && (
            <div key={bubble} className="bubble">
              {bubble}
              {last && (
                <small>
                  {last.outcome === 'draw'
                    ? `We both picked ${set.byId[last.child].label}`
                    : WINS_BECAUSE[last.outcome === 'win' ? last.child : last.robot]}
                </small>
              )}
            </div>
          )}
          {last && <Badge gesture={last.robot} set={set} mark={markFor(last.outcome, 'coral')} who="coral" />}
        </section>

        <section className="right">
          {phase === 'ready' ? (
            <div className="start">
              <div className="start-moves">
                {set.gestures.map((g) => (
                  <div key={g.id} className={`start-move ${matched === g.id ? 'lit' : ''}`} style={{ '--c': MOVE_COLOR[g.id] } as React.CSSProperties}>
                    <ScoreRing score={shown?.[g.id] ?? null}>
                      <PoseArt gesture={g} />
                    </ScoreRing>
                    <b>{g.label}</b>
                  </div>
                ))}
              </div>
              <button className="big-btn" onClick={playMatch}>
                Start
              </button>
            </div>
          ) : phase === 'final' ? (
            <FinalPanel results={results} set={set} you={you} coral={coral} onAgain={playMatch} />
          ) : (
            <>
              <div className="beam" />
              <CoralEye
                body={body}
                color={lit ? MOVE_COLOR[lit] : null}
                fits={phase === 'position' ? fit === 'fit' : undefined}
                open
              />
              {last && <Badge gesture={last.child} set={set} mark={markFor(last.outcome, 'child')} who="you" />}
            </>
          )}
        </section>
      </main>

      {playing && (
        <footer className="moves">
          {set.gestures.map((g) => (
            <div
              key={g.id}
              className={`move ${lit === g.id ? 'lit' : ''} ${phase === 'captured' && youMove === g.id ? 'locked' : ''}`}
              style={{ '--c': MOVE_COLOR[g.id] } as React.CSSProperties}
            >
              <ScoreRing score={phase === 'captured' ? null : shown?.[g.id] ?? null}>
                <PoseArt gesture={g} color={lit === g.id ? undefined : '#B9AFC4'} />
              </ScoreRing>
              <b>{g.label}</b>
            </div>
          ))}
        </footer>
      )}

      {phase === 'countdown' && (
        <div key={count} className={`count-word w-${count.toLowerCase()}`}>
          {count === 'Shoot' ? 'SHOOT!' : `${count}…`}
        </div>
      )}

      {last && (
        <button className="next-btn" onClick={() => nextRef.current?.()}>
          {results.length >= ROUNDS ? 'See who won' : 'Next round'}
        </button>
      )}

      {phase === 'final' && <Confetti />}
      {help && <HowToPlay set={set} onClose={() => setHelp(false)} />}
    </div>
  )
}

/** Red at 0, through yellow, to green at the MATCH line, where a move counts. */
const scoreColor = (s: number) => `hsl(${Math.round(Math.min(1, s / MATCH) * 120)} 80% 45%)`

const RING_R = 54
const RING_LEN = 2 * Math.PI * RING_R

/**
 * How close the child's pose is to one move: a ring that fills and turns from
 * red to green as the similarity score rises, with the score in the middle of
 * its edge. `null` (no one in view, or the move is already locked in) hides it.
 */
function ScoreRing({ score, children }: { score: number | null; children: React.ReactNode }) {
  const s = score ?? 0
  return (
    <div className={`score-ring ${score === null ? 'off' : ''}`} style={{ '--sc': scoreColor(s) } as React.CSSProperties}>
      <svg viewBox="0 0 120 120" aria-hidden>
        <circle cx="60" cy="60" r={RING_R} className="track" />
        {s >= 0.01 && <circle cx="60" cy="60" r={RING_R} className="arc" strokeDasharray={`${s * RING_LEN} ${RING_LEN}`} />}
        <line
          className="goal"
          x1="60"
          y1={60 - RING_R - 7}
          x2="60"
          y2={60 - RING_R + 7}
          transform={`rotate(${MATCH * 360} 60 60)`}
        />
      </svg>
      <div className="art">{children}</div>
      {score !== null && <span className="pct">{Math.round(s * 100)}%</span>}
    </div>
  )
}

type Mark = 'star' | 'frown' | 'equal'

function markFor(outcome: Outcome, side: 'child' | 'coral'): Mark {
  if (outcome === 'draw') return 'equal'
  return (outcome === 'win') === (side === 'child') ? 'star' : 'frown'
}

function MarkIcon({ mark }: { mark: Mark }) {
  return (
    <span className={`mark ${mark}`} aria-label={mark}>
      <svg viewBox="0 0 24 24" aria-hidden>
        {mark === 'star' && <path d="M12 2.5l2.9 6 6.6.8-4.9 4.6 1.3 6.5L12 17.2l-5.9 3.2 1.3-6.5L2.5 9.3l6.6-.8z" />}
        {mark === 'frown' && (
          <>
            <circle cx="12" cy="12" r="10" />
            <circle cx="8.6" cy="9.6" r="1.4" className="cut" />
            <circle cx="15.4" cy="9.6" r="1.4" className="cut" />
            <path d="M7.8 16.6q4.2-3.6 8.4 0" className="cut-line" />
          </>
        )}
        {mark === 'equal' && (
          <>
            <rect x="4" y="7.5" width="16" height="3.4" rx="1.7" />
            <rect x="4" y="13.1" width="16" height="3.4" rx="1.7" />
          </>
        )}
      </svg>
    </span>
  )
}

/** A big round badge showing one player's move in the reveal. */
function Badge({ gesture, set, mark, who }: { gesture: GestureId; set: GestureSet; mark: Mark; who: 'you' | 'coral' }) {
  return (
    <div className={`badge reveal ${who} ${mark}`} style={{ '--c': MOVE_COLOR[gesture] } as React.CSSProperties}>
      <div className="disc">
        <PoseArt gesture={set.byId[gesture]} />
      </div>
      <b>{who === 'you' ? 'You' : 'CORAL'}</b>
      <MarkIcon mark={mark} />
    </div>
  )
}

/** Score in the display font, with a dot per round. */
function Scoreboard({ results, round, you, coral }: { results: RoundResult[]; round: number; you: number; coral: number }) {
  return (
    <div className="scoreboard">
      <span className="who">You</span>
      <span key={`y${you}`} className="n you">{you}</span>
      <div className="dots">
        {Array.from({ length: ROUNDS }, (_, i) => (
          <span key={i} className={`dot ${i < results.length ? results[i].outcome : i === round - 1 ? 'now' : ''}`} />
        ))}
      </div>
      <span key={`c${coral}`} className="n coral">{coral}</span>
      <span className="who">CORAL</span>
    </div>
  )
}

function FinalPanel({
  results,
  set,
  you,
  coral,
  onAgain,
}: {
  results: RoundResult[]
  set: GestureSet
  you: number
  coral: number
  onAgain: () => void
}) {
  return (
    <div className="final">
      <div className="final-score">
        <span className="you">{you}</span>
        <span className="dash">–</span>
        <span className="coral">{coral}</span>
      </div>
      <div className="final-rounds">
        {results.map((r, i) => (
          <div key={i} className={`round-badge ${markFor(r.outcome, 'child')}`} style={{ '--c': MOVE_COLOR[r.child] } as React.CSSProperties}>
            <PoseArt gesture={set.byId[r.child]} />
            <MarkIcon mark={markFor(r.outcome, 'child')} />
          </div>
        ))}
      </div>
      <button className="big-btn" onClick={onAgain}>
        Play again
      </button>
    </div>
  )
}

function Confetti() {
  const pieces = useMemo(
    () =>
      Array.from({ length: 80 }, (_, i) => ({
        left: `${Math.random() * 100}%`,
        background: ['#FF7A59', MOVE_COLOR.rock, MOVE_COLOR.paper, MOVE_COLOR.scissors, '#FFD54F'][i % 5],
        animationDuration: `${2.4 + Math.random() * 2}s`,
        animationDelay: `${Math.random() * 1.2}s`,
      })),
    [],
  )
  return (
    <div className="confetti">
      {pieces.map((style, i) => (
        <i key={i} style={style} />
      ))}
    </div>
  )
}

/** For the grown-up: how to make each move, from the corner menu. */
function HowToPlay({ set, onClose }: { set: GestureSet; onClose: () => void }) {
  return (
    <div className="help" onClick={onClose}>
      <div className="help-card" onClick={(e) => e.stopPropagation()}>
        <h2>How to play</h2>
        <div className="help-moves">
          {set.gestures.map((g) => (
            <div key={g.id} className="help-move" style={{ '--c': MOVE_COLOR[g.id] } as React.CSSProperties}>
              <PoseArt gesture={g} />
              <b>{g.label}</b>
              <p>{g.tip}</p>
              <p className="beats">Beats {set.byId[BEATS[g.id]].label}</p>
            </div>
          ))}
        </div>
        <p className="help-note">Stand so CORAL can see your head and shoulders (the frame turns green); sitting close is fine. When CORAL says Shoot, hold your move until it says “Got it”.</p>
        <button className="big-btn small" onClick={onClose}>
          OK
        </button>
      </div>
    </div>
  )
}
