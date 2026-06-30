import { useMemo } from 'react'
import { RobotWaving } from './Characters'

const STARS = ['⭐', '🌟', '✨', '💫', '🎉', '🎊', '🌈', '❤️', '💜', '🦋']

function randomBetween(a: number, b: number) {
  return a + Math.random() * (b - a)
}

export default function Page8_Outro() {
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

      <RobotWaving width={200} />

      <div className="p8-subtitle">
        Great job teaching Coral your poses!
      </div>
    </div>
  )
}
