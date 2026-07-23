import { useEffect, useMemo, useRef, useState } from 'react'

// Alternating slice fills — brand orange against graphite, plus a gold for the
// rare top prize so the jackpot slice reads as special.
const SLICE_FILLS = ['#1E2025', '#E8450A', '#17181C', '#C93A08']
const JACKPOT_FILL = '#E0A106'

const R = 95
const C = 100

function polar(cx, cy, r, angleDeg) {
  const a = ((angleDeg - 90) * Math.PI) / 180
  return [cx + r * Math.cos(a), cy + r * Math.sin(a)]
}

function slicePath(index, count) {
  const span = 360 / count
  const start = index * span
  const end = start + span
  const [x1, y1] = polar(C, C, R, start)
  const [x2, y2] = polar(C, C, R, end)
  const large = span > 180 ? 1 : 0
  return `M ${C} ${C} L ${x1.toFixed(2)} ${y1.toFixed(2)} A ${R} ${R} 0 ${large} 1 ${x2.toFixed(2)} ${y2.toFixed(2)} Z`
}

/**
 * Wheel of Fortune.
 *
 * `segments` is [{amount, weight}] in the same order the backend draws from, so
 * `landOn` (the server's chosen segment index) maps straight to a slice. When
 * `landOn` becomes a number the wheel spins several turns and settles with that
 * slice under the top pointer, then calls `onSettle`.
 */
export default function Wheel({ segments, landOn = null, onSettle, idle = false }) {
  const count = segments.length
  const span = 360 / count
  const [rotation, setRotation] = useState(0)
  const [spinning, setSpinning] = useState(false)

  // Keep the latest onSettle without making it an effect dependency, so the
  // spin schedules exactly once per landOn (and survives StrictMode's
  // mount/cleanup/mount without the timeout being permanently cancelled).
  const onSettleRef = useRef(onSettle)
  onSettleRef.current = onSettle

  const max = useMemo(
    () => segments.reduce((m, s) => Math.max(m, parseFloat(s.amount)), 0),
    [segments]
  )

  useEffect(() => {
    if (landOn == null || landOn < 0 || landOn >= count) return
    // Land the chosen slice's centre under the pointer at 12 o'clock: rotate so
    // that centre angle maps to 0, plus a handful of full turns for the spin.
    const centre = landOn * span + span / 2
    const target = 360 * 6 - centre
    setSpinning(true)
    // Next frame so the transition actually animates from the current value.
    const id = requestAnimationFrame(() => setRotation(target))
    const done = setTimeout(() => {
      setSpinning(false)
      onSettleRef.current?.(landOn)
    }, 4200)
    return () => {
      cancelAnimationFrame(id)
      clearTimeout(done)
    }
  }, [landOn, count, span])

  return (
    <div className="relative mx-auto aspect-square w-full max-w-[20rem]">
      {/* Pointer */}
      <div className="absolute left-1/2 top-0 z-10 -translate-x-1/2 -translate-y-1/2">
        <div
          className="h-0 w-0 border-x-[10px] border-t-[16px] border-x-transparent border-t-accent drop-shadow"
          style={{ transform: 'rotate(180deg)' }}
        />
      </div>

      <svg
        viewBox="0 0 200 200"
        className="h-full w-full drop-shadow-[0_0_30px_rgba(232,69,10,0.15)]"
      >
        <circle cx={C} cy={C} r={R + 3} fill="#0B0C0E" stroke="#26292F" strokeWidth="2" />
        <g
          className={idle && landOn == null ? 'wheel-idle' : undefined}
          style={
            idle && landOn == null
              ? undefined
              : {
                  transformOrigin: '100px 100px',
                  transform: `rotate(${rotation}deg)`,
                  transition: spinning
                    ? 'transform 4s cubic-bezier(0.16, 1, 0.3, 1)'
                    : 'none',
                }
          }
        >
          {segments.map((s, i) => {
            const amt = parseFloat(s.amount)
            const isJackpot = amt === max
            const fill = isJackpot ? JACKPOT_FILL : SLICE_FILLS[i % SLICE_FILLS.length]
            const mid = i * span + span / 2
            const [tx, ty] = polar(C, C, R * 0.66, mid)
            return (
              <g key={i}>
                <path d={slicePath(i, count)} fill={fill} stroke="#0B0C0E" strokeWidth="1" />
                <text
                  x={tx}
                  y={ty}
                  fill="#fff"
                  fontSize="13"
                  fontWeight="800"
                  textAnchor="middle"
                  dominantBaseline="middle"
                  transform={`rotate(${mid}, ${tx}, ${ty})`}
                  style={{ fontStyle: 'italic' }}
                >
                  ${amt}
                </text>
              </g>
            )
          })}
        </g>
        {/* Hub */}
        <circle cx={C} cy={C} r="14" fill="#121316" stroke="#E8450A" strokeWidth="2" />
      </svg>
    </div>
  )
}
