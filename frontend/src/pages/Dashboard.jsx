import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import client from '../api/client'
import Logo from '../components/Logo'
import { useAuth } from '../context/AuthContext'
import { money, formatDate, signedMoney } from '../lib/format'

export default function Dashboard() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const [matches, setMatches] = useState([])
  const [matchesLoaded, setMatchesLoaded] = useState(false)

  useEffect(() => {
    let active = true
    client
      .get('/me/matches')
      .then(({ data }) => {
        if (active) setMatches(Array.isArray(data) ? data : [])
      })
      .catch(() => {
        if (active) setMatches([])
      })
      .finally(() => {
        if (active) setMatchesLoaded(true)
      })
    return () => {
      active = false
    }
  }, [])

  return (
    <div className="min-h-screen bg-graphite-950 text-steel-100">
      <header className="sticky top-0 z-40 border-b border-line-dark bg-graphite-950/90 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-5xl items-center justify-between px-4 sm:px-6">
          <Logo to="/tables" light />
          <div className="flex items-center gap-3">
            <div className="hidden text-right sm:block">
              <div className="text-[10px] uppercase tracking-[0.24em] text-steel-500">
                Balance
              </div>
              <div className="font-display text-lg font-semibold leading-none text-white">
                {user ? money(user.balance) : '-'}
              </div>
            </div>
            <button
              type="button"
              onClick={() => navigate('/wallet')}
              className="rounded-md border border-line-dark px-3 py-2 text-xs font-semibold uppercase tracking-wide text-steel-100 transition-colors hover:border-accent hover:text-accent sm:px-4"
            >
              Wallet
            </button>
            <button
              type="button"
              onClick={() => navigate('/tables')}
              className="rounded-md bg-accent px-3 py-2 text-xs font-semibold uppercase tracking-wide text-white transition-colors hover:bg-accent-dark sm:px-4"
            >
              Tables
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-4 pb-20 pt-8 sm:px-6 sm:pt-10">
        {/* Profile summary. Wallet page owns deposit/withdraw; here it's just
            identity and a nudge back to /tables. */}
        <section className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-[10px] font-medium uppercase tracking-[0.3em] text-accent">
              {user?.faceit_username || 'Player'}
            </p>
            <h1 className="mt-2 font-display text-4xl font-black uppercase italic leading-none tracking-tight text-white sm:text-5xl">
              Your history
            </h1>
          </div>
          <div className="text-right sm:hidden">
            <div className="text-[10px] uppercase tracking-[0.24em] text-steel-500">
              Balance
            </div>
            <div className="font-display text-2xl font-bold leading-none text-white">
              {user ? money(user.balance) : '-'}
            </div>
          </div>
        </section>

        {/* Recent matches. Card list on phones (five columns won't fit a
            375px viewport without a horizontal scroller); a real table from
            sm+. */}
        <section className="mt-8 sm:mt-10">
          <h2 className="text-[10px] font-medium uppercase tracking-[0.28em] text-steel-500">
            Recent matches
          </h2>

          {matchesLoaded && matches.length === 0 && (
            <p className="mt-6 text-sm text-steel-500">
              No matches yet. Head to the tables to open your first.
            </p>
          )}

          {matches.length > 0 && (
            <>
              <ul className="mt-3 divide-y divide-line-dark border-y border-line-dark sm:hidden">
                {matches.map((m) => (
                  <MatchCard key={m.id} match={m} />
                ))}
              </ul>

              <table className="mt-4 hidden w-full text-sm sm:table">
                <thead>
                  <tr className="border-b border-line-dark text-left text-steel-500">
                    <th className="py-2 text-[10px] font-medium uppercase tracking-[0.2em]">
                      Format
                    </th>
                    <th className="py-2 text-[10px] font-medium uppercase tracking-[0.2em]">
                      Opponent
                    </th>
                    <th className="py-2 text-[10px] font-medium uppercase tracking-[0.2em]">
                      Stake
                    </th>
                    <th className="py-2 text-[10px] font-medium uppercase tracking-[0.2em]">
                      Result
                    </th>
                    <th className="py-2 text-[10px] font-medium uppercase tracking-[0.2em]">
                      Payout
                    </th>
                    <th className="py-2 text-[10px] font-medium uppercase tracking-[0.2em]">
                      Date
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line-dark">
                  {matches.map((m) => (
                    <MatchRow key={m.id} match={m} />
                  ))}
                </tbody>
              </table>
            </>
          )}
        </section>
      </main>
    </div>
  )
}

function fmt(match) {
  const size = match.team_size ?? 1
  return `${size}v${size}`
}

function MatchRow({ match }) {
  const opponent = match.opponent_username || '-'
  const result = match.result ?? null
  const isWin = result === 'W' || result === 'win'
  const isLoss = result === 'L' || result === 'loss'
  return (
    <tr className="text-steel-100">
      <td className="py-3 font-display text-sm font-bold italic text-accent">
        {fmt(match)}
      </td>
      <td className="py-3">{opponent}</td>
      <td className="py-3 text-steel-400">{money(match.wager_amount)}</td>
      <td className="py-3">
        {isWin ? (
          <span className="font-medium text-win">Won</span>
        ) : isLoss ? (
          <span className="font-medium text-loss">Lost</span>
        ) : (
          <span className="text-steel-500">{match.status || '-'}</span>
        )}
      </td>
      <td
        className={`py-3 font-medium ${isWin ? 'text-win' : isLoss ? 'text-loss' : 'text-steel-500'}`}
      >
        {match.payout != null ? signedMoney(match.payout) : '-'}
      </td>
      <td className="py-3 text-steel-500">{formatDate(match.created_at)}</td>
    </tr>
  )
}

function MatchCard({ match }) {
  const opponent = match.opponent_username || '-'
  const result = match.result ?? null
  const isWin = result === 'W' || result === 'win'
  const isLoss = result === 'L' || result === 'loss'
  return (
    <li className="flex items-center justify-between gap-3 py-3">
      <div className="min-w-0">
        <div className="flex items-baseline gap-2">
          <span className="font-display text-sm font-bold italic text-accent">
            {fmt(match)}
          </span>
          <span className="truncate text-sm font-medium text-steel-100">
            vs {opponent}
          </span>
        </div>
        <div className="mt-0.5 text-[11px] text-steel-500">
          {money(match.wager_amount)} · {formatDate(match.created_at)}
        </div>
      </div>
      <div className="shrink-0 text-right">
        {isWin || isLoss ? (
          <div
            className={`font-display text-sm font-bold ${isWin ? 'text-win' : 'text-loss'}`}
          >
            {match.payout != null ? signedMoney(match.payout) : result}
          </div>
        ) : (
          <div className="text-xs text-steel-500">{match.status || '-'}</div>
        )}
      </div>
    </li>
  )
}
