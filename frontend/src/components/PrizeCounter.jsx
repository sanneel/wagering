import { useEffect, useRef, useState } from 'react'

// A slot-machine / odometer prize reveal: a row of digit reels that spin and
// settle on the prize amount, left reel last for a cascading stop. This is the
// SpinCounter's namesake — a counter that spins — used instead of a wheel.

const CELL = 56 // px height of one digit cell (must match --prize-cell in CSS)
const CYCLES = 5 // full 0–9 spins before a reel lands
const IDLE_STRIP = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9]

function digitsOf(amount, slots) {
  const n = Math.max(0, Math.round(Number(amount) || 0))
  const s = String(n)
  const len = Math.max(slots, s.length)
  return s.padStart(len, '0').split('').map(Number)
}

/**
 * @param amount   the prize to reveal (number of currency units)
 * @param landOn   when truthy, the reels spin once and settle on `amount`
 * @param onSettle called after the last reel comes to rest
 * @param idle     decorative endless roll (hero); ignores amount/landOn
 * @param slots    number of digit reels (leading zeros pad shorter prizes)
 */
export default function PrizeCounter({
  amount = 0,
  landOn = false,
  onSettle,
  idle = false,
  slots = 4,
}) {
  const digits = digitsOf(amount, slots)
  const n = digits.length

  // Keep the latest onSettle out of the effect deps so the spin schedules once
  // per landOn and survives StrictMode's mount/cleanup/mount.
  const onSettleRef = useRef(onSettle)
  onSettleRef.current = onSettle

  const [rolling, setRolling] = useState(false)
  const [positions, setPositions] = useState(() => digits.map((d) => d))

  useEffect(() => {
    if (idle || !landOn) return
    setRolling(true)
    setPositions(digits.map(() => 0))
    const raf = requestAnimationFrame(() =>
      setPositions(digits.map((d) => CYCLES * 10 + d))
    )
    const maxDur = 2200 + (n - 1) * 350
    const done = setTimeout(() => {
      setRolling(false)
      onSettleRef.current?.()
    }, maxDur + 250)
    return () => {
      cancelAnimationFrame(raf)
      clearTimeout(done)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [landOn, idle])

  const stripLen = CYCLES * 10 + 10
  const strip = Array.from({ length: stripLen }, (_, j) => j % 10)

  return (
    <div className="flex items-center justify-center gap-1.5">
      <span className="mb-1 font-display text-3xl font-black italic text-accent">$</span>
      {digits.map((d, i) => (
        <div key={i} className="prize-reel" style={{ height: CELL, width: CELL * 0.82 }}>
          {idle ? (
            <div
              className="prize-strip prize-strip-idle"
              style={{ animationDuration: `${0.7 + i * 0.18}s` }}
            >
              {IDLE_STRIP.map((x, j) => (
                <span key={j} className="prize-digit" style={{ height: CELL }}>
                  {x}
                </span>
              ))}
            </div>
          ) : (
            <div
              className="prize-strip"
              style={{
                transform: `translateY(-${positions[i] * CELL}px)`,
                transition: rolling
                  ? `transform ${2200 + (n - 1 - i) * 350}ms cubic-bezier(0.16, 1, 0.3, 1)`
                  : 'none',
              }}
            >
              {strip.map((x, j) => (
                <span key={j} className="prize-digit" style={{ height: CELL }}>
                  {x}
                </span>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
