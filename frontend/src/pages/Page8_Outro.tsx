import { useMemo } from 'react'
import { RobotWaving } from './Characters'
import { DummyFrame } from './DummyStream'
import type { PageProps } from './TestUIRouter'

const STARS = ['⭐', '🌟', '✨', '💫', '🎉', '🎊', '🌈', '❤️', '💜', '🦋']

function randomBetween(a: number, b: number) {
  return a + Math.random() * (b - a)
}

export default function Page8_Outro({ state }: PageProps) {
  const stars = useMemo(
    () =>
      Array.from({ length: 18 }).map((_, i) => ({
        id: i,
        emoji: STARS[i % STARS.length],
        left: randomBetween(2, 96),
        delay: randomBetween(0, 6),
        duration: randomBetween(4, 8),
        size: randomBetween(16, 28),
      })),
    [],
  )

  const moves = state.moves

  return (
    <div className="tui-page p8-layout">
      {/* Falling confetti */}
      {stars.map((s) => (
        <div
          key={s.id}
          className="p8-star"
          style={{
            left: `${s.left}%`,
            fontSize: s.size,
            animationDelay: `${s.delay}s`,
            animationDuration: `${s.duration}s`,
          }}
        >
          {s.emoji}
        </div>
      ))}

      <div className="p8-thank-you">Thank You! 🎉</div>

      {moves.length > 0 ? (
        <>
          <div className="p8-subtitle">You taught Coral {moves.length} move{moves.length === 1 ? '' : 's'}!</div>
          <div className="p8-moves">
            {moves.map((m, i) => (
              <div className="p8-move-card tui-pop" key={i} style={{ animationDelay: `${0.1 + i * 0.1}s` }}>
                {m.frame ? (
                  <img
                    className="p8-move-img"
                    src={`data:image/jpeg;base64,${m.frame}`}
                    alt={m.name}
                  />
                ) : (
                  <DummyFrame className="p8-move-img" />
                )}
                <div className="p8-move-name">"{m.name}"</div>
              </div>
            ))}
          </div>
        </>
      ) : (
        <>
          <RobotWaving width={200} />
          <div className="p8-subtitle">Great job teaching Coral your poses!</div>
        </>
      )}
    </div>
  )
}
