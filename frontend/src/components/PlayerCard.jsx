import { money } from '../lib/format'

// `border` may be 'win' | 'loss' | undefined for the neutral lobby state.
export default function PlayerCard({ player, border, payout }) {
  const name = player?.faceit_username || player?.username || 'Unknown'
  const elo = player?.faceit_elo ?? player?.elo
  const avatar = player?.avatar || player?.faceit_avatar

  const borderClass =
    border === 'win'
      ? 'border-win'
      : border === 'loss'
        ? 'border-loss'
        : 'border-line'

  return (
    <div
      className={`flex w-full flex-col items-center rounded-lg border ${borderClass} bg-white p-6`}
    >
      <div className="h-16 w-16 overflow-hidden rounded-full border border-line bg-gray-100">
        {avatar ? (
          <img
            src={avatar}
            alt={name}
            className="h-full w-full object-cover"
            onError={(e) => {
              e.currentTarget.style.display = 'none'
            }}
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-lg font-semibold text-muted">
            {name.slice(0, 1).toUpperCase()}
          </div>
        )}
      </div>
      <div className="mt-3 text-center">
        <div className="font-medium text-ink">{name}</div>
        {elo != null && (
          <div className="text-sm text-muted">ELO {elo}</div>
        )}
      </div>
      {border === 'win' && payout != null && (
        <div className="mt-3 text-lg font-semibold text-win">
          +{money(payout)}
        </div>
      )}
      {border === 'loss' && payout != null && (
        <div className="mt-3 text-lg font-semibold text-loss">
          -{money(Math.abs(payout))}
        </div>
      )}
    </div>
  )
}
