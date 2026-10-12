import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { LiveStream } from './DummyStream'
import RobotViewer from '../components/RobotViewer'
import { usePoseWebSocket } from '../hooks/usePoseWebSocket'
import { killSpeech, resetPose, speak, stopSubjectSelection } from '../demo/api'
import GestureFigure from '../rps/GestureFigure'
import SkeletonView, { followReadiness } from '../rps/SkeletonView'
import RpsTopbar, { RPS_PATH } from '../rps/RpsTopbar'
import { gestureScores } from '../rps/classify'
import { customGestureSet } from '../rps/customMoves'
import { STANDARD_SET } from '../rps/gestureSet'
import { poseRobot, resetRobot } from '../rps/robotPose'
import { BEATS, GESTURES, type GestureId } from '../rps/gestures'
import './RefinedDemo.css'
import './RockPaperScissors.css'

type Outcome = 'win' | 'lose' | 'draw'
type Phase = 'ready' | 'position' | 'countdown' | 'shoot' | 'result' | 'retry' | 'summary'

interface RoundResult {
  child: GestureId
  robot: GestureId
  outcome: Outcome
  /** Best similarity (0-1) of the child's pose to the move they made, during the shoot window. */
  similarity: number
  /** Time from "Shoot!" until the camera first saw that move, in ms. Kept for data logging later. */
  reactionMs: number
}

const ROUNDS = 3
const COUNTDOWN_WORDS = ['ROCK', 'PAPER', 'SCISSORS']
const WORD_MS = 900
const SAMPLE_WINDOW_MS = 1300
const SAMPLE_EVERY_MS = 50
const RESULT_MS = 3500
const RETRY_MS = 3000
/** Before the first round: give the child time to step back, then wait until both arms are in view this long. */
const POSITION_MIN_MS = 2000
const POSITION_STEADY_MS = 1000

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))

function judge(child: GestureId, robot: GestureId): Outcome {
  if (child === robot) return 'draw'
  return BEATS[child] === robot ? 'win' : 'lose'
}

const ROUND_TEXT: Record<Outcome, string> = {
  win: 'You win this round!',
  lose: 'CORAL wins this round!',
  draw: "It's a draw!",
}

function say(text: string) {
  killSpeech()
    .then(() => speak({ text }))
    .catch(() => {})
}

/** Play screen: three rounds against CORAL, laid out as in the game wireframes. */
export default function RpsPlay() {
  const [params] = useSearchParams()
  const wantsCustom = params.get('moves') === 'custom'
  const set = useMemo(() => (wantsCustom ? customGestureSet() : STANDARD_SET), [wantsCustom])

  const { bodyLandmarks, trackingLost } = usePoseWebSocket()
  const body = trackingLost ? [] : bodyLandmarks

  const [phase, setPhase] = useState<Phase>('ready')
  const [round, setRound] = useState(1)
  const [word, setWord] = useState(0)
  const [results, setResults] = useState<RoundResult[]>([])

  const scores = useMemo(() => (set ? gestureScores(body, set) : null), [body, set])
  // It's a game, not a test: whichever move the pose is most similar to counts,
  // with no minimum score. Learn keeps the stricter check for teaching.
  // Null only when the arms can't be seen.
  const detected = useMemo(
    () => (scores ? GESTURES.reduce((a, g) => (scores[g.id] > scores[a] ? g.id : a), GESTURES[0].id) : null),
    [scores],
  )
  const readiness = followReadiness(body)

  // The game loop samples the camera outside React's render cycle.
  const detectedRef = useRef(detected)
  detectedRef.current = detected
  const scoresRef = useRef(scores)
  scoresRef.current = scores
  const readyRef = useRef(readiness.ok)
  readyRef.current = readiness.ok

  const runIdRef = useRef(0)

  useEffect(() => {
    stopSubjectSelection()
    resetRobot().catch(() => {})
    return () => {
      runIdRef.current++
      killSpeech()
      resetPose().catch(() => {})
    }
  }, [])

  const playRound = useCallback(
    async (cancelled: () => boolean): Promise<RoundResult | null> => {
      if (!set) return null
      await resetRobot().catch((e) => console.warn('robot reset failed', e))

      setPhase('countdown')
      for (let i = 0; i < COUNTDOWN_WORDS.length; i++) {
        if (cancelled()) return null
        setWord(i)
        await sleep(WORD_MS)
      }
      if (cancelled()) return null

      // Shoot: the robot strikes its move while the camera watches the child.
      setPhase('shoot')
      const robot = set.gestures[Math.floor(Math.random() * set.gestures.length)].id
      // The robot moves at gentle follow speed, so a big swing can outlast the sampling window.
      const robotMove = poseRobot(set.byId[robot].robotPulses).catch((e) => console.warn('robot move failed', e))

      const votes: Record<GestureId, number> = { rock: 0, paper: 0, scissors: 0 }
      const best: Record<GestureId, number> = { rock: 0, paper: 0, scissors: 0 }
      const firstSeen: Partial<Record<GestureId, number>> = {}
      const start = Date.now()
      while (Date.now() - start < SAMPLE_WINDOW_MS) {
        if (cancelled()) return null
        const seen = detectedRef.current
        if (seen) {
          votes[seen]++
          firstSeen[seen] ??= Date.now() - start
        }
        const s = scoresRef.current
        if (s) for (const g of GESTURES) best[g.id] = Math.max(best[g.id], s[g.id])
        await sleep(SAMPLE_EVERY_MS)
      }
      if (cancelled()) return null
      // Show the verdict only once CORAL has finished its move.
      await robotMove
      if (cancelled()) return null

      const top = (Object.keys(votes) as GestureId[]).reduce((a, b) => (votes[b] > votes[a] ? b : a))
      if (votes[top] === 0) return null
      return {
        child: top,
        robot,
        outcome: judge(top, robot),
        similarity: best[top],
        reactionMs: firstSeen[top] ?? 0,
      }
    },
    [set],
  )

  const playMatch = useCallback(async () => {
    if (!set) return
    const run = ++runIdRef.current
    const cancelled = () => run !== runIdRef.current
    setResults([])
    setRound(1)

    // The child clicked Ready at the computer: wait for them to step back into view.
    setPhase('position')
    say('Step back so I can see both of your arms!')
    const begin = Date.now()
    let steadySince: number | null = null
    while (true) {
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
      if (cancelled()) return
      if (!r) {
        setPhase('retry')
        say("I couldn't see your move! Let's try that round again.")
        await sleep(RETRY_MS)
        continue
      }
      done.push(r)
      setResults([...done])
      setPhase('result')
      say(`You chose ${set.byId[r.child].label}. I chose ${set.byId[r.robot].label}. ${ROUND_TEXT[r.outcome]}`)
      await sleep(RESULT_MS)
    }
    if (cancelled()) return

    setPhase('summary')
    const you = done.filter((r) => r.outcome === 'win').length
    const coral = done.filter((r) => r.outcome === 'lose').length
    say(you > coral ? 'You win! Great game!' : coral > you ? 'I win this time! Want a rematch?' : "It's a tie! Let's have a rematch!")
  }, [set, playRound])

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

  const you = results.filter((r) => r.outcome === 'win').length
  const coral = results.filter((r) => r.outcome === 'lose').length
  const last = phase === 'result' || phase === 'summary' ? results[results.length - 1] : null
  const busy = phase !== 'ready' && phase !== 'summary'

  let banner: string
  if (phase === 'ready') banner = 'Press Ready when you want to start!'
  else if (phase === 'position') banner = readiness.ok ? 'Great, hold on…' : 'Step back so I can see both of your arms.'
  else if (phase === 'countdown' || phase === 'shoot') banner = 'Get ready to make your move!'
  else if (phase === 'retry') banner = "I couldn't see your move! Let's try that round again."
  else if (last) banner = `You chose ${set.byId[last.child].label}. CORAL chose ${set.byId[last.robot].label}. ${ROUND_TEXT[last.outcome]}`
  else banner = ''

  // Live similarity while playing; the round's own score once it is decided.
  const similarityText = last
    ? `${set.byId[last.child].label}: ${Math.round(last.similarity * 100)}%`
    : scores && detected
    ? `${set.byId[detected].label}: ${Math.round(scores[detected] * 100)}%`
    : '—'

  return (
    <div className="rd-root">
      <RpsTopbar busy={busy} />

      <div className="rps-play-head">
        <div className="rps-play-status">
          <div className="rps-round">
            ROUND {round}/{ROUNDS}
            {set.kind === 'custom' && <span className="rps-tag">Your moves</span>}
          </div>
          <div className="rps-score">
            YOU {you} <span>|</span> CORAL {coral}
          </div>
        </div>
        <div className={`rps-banner ${last && phase === 'result' ? last.outcome : ''}`}>{banner}</div>
        <div className="rps-cheats" aria-label="Cheat sheet">
          {set.gestures.map((g) => (
            <div key={g.id} className="rps-cheat">
              <GestureFigure gesture={g} />
              <span>{g.label}</span>
            </div>
          ))}
        </div>
      </div>

      <main className="rps-stage">
        <div className="rps-trio">
          <div className="rps-cell">
            <div className="rd-sim-grid" />
            <div className="rd-sim-vignette" />
            <div className="rps-cell-title">CORAL</div>
            <RobotViewer embedded />
            <div className="rps-caption">{last ? set.byId[last.robot].label : '?'}</div>
          </div>
          <div className="rps-cell rps-cell-dark">
            <div className="rps-cell-title">You</div>
            <LiveStream badge={false} />
            <div className="rps-caption">
              {last ? set.byId[last.child].label : detected ? set.byId[detected].label : '?'}
            </div>
          </div>
          <div className="rps-cell rps-cell-dark">
            <div className="rps-cell-title">What I think your pose is</div>
            <SkeletonView landmarks={body} />
            {!readiness.ok && <div className="rps-note warn">{readiness.message}</div>}
            <div className="rps-caption">Similarity score · {similarityText}</div>
          </div>
        </div>

        {phase === 'ready' && (
          <div className="rps-overlay">
            <button className="rps-big-btn" onClick={playMatch}>
              Ready?
            </button>
          </div>
        )}

        {(phase === 'countdown' || phase === 'shoot') && (
          <div className="rps-overlay">
            <div className="rps-words">
              {COUNTDOWN_WORDS.map((w, i) => (
                <span key={w} className={phase === 'countdown' && i === word ? 'on' : ''}>
                  {w}
                </span>
              ))}
              <span className={`shoot ${phase === 'shoot' ? 'on' : ''}`}>SHOOT!</span>
            </div>
          </div>
        )}
      </main>

      {phase === 'summary' && (
        <div className="rd-countdown-modal">
          <div className="rps-summary">
            <div className="rps-summary-score">
              <div className="rps-summary-label">SCORE</div>
              YOU: {you} | CORAL: {coral}
            </div>
            <div className={`rps-summary-verdict ${you > coral ? 'win' : coral > you ? 'lose' : 'draw'}`}>
              {you > coral ? 'YOU WIN! YAY!' : coral > you ? 'CORAL WINS!' : "IT'S A TIE!"}
            </div>
            <div className="rps-summary-actions">
              <button className="rps-big-btn" onClick={playMatch}>
                Rematch
              </button>
              <Link to={RPS_PATH} className="rps-big-btn ghost">
                Menu
              </Link>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
