import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import client from '../api/client'
import TopNav from '../components/TopNav'
import { money, formatDate } from '../lib/format'

export default function Dashboard() {
  const navigate = useNavigate()
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
    <div className="min-h-screen">
      <TopNav />

      <main className="mx-auto max-w-5xl px-4 py-10">
        {/* Opening and joining now lives on /tables, which owns the formats,
            stakes and seat state. This just points there rather than keeping a
            second, 1v1-only create form in sync with it. */}
        <section>
          <h1 className="text-xl font-semibold text-ink">Play</h1>
          <p className="mt-1 text-sm text-muted">
            Open a table or take a seat. 1v1, 2v2 or 5v5.
          </p>
          <button
            type="button"
            onClick={() => navigate('/tables')}
            className="mt-5 rounded-md bg-accent px-5 py-2.5 text-sm font-medium text-white hover:bg-accent-dark"
          >
            Browse tables
          </button>
        </section>

        {/* Recent matches */}
        <section className="mt-12">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">
            Your recent matches
          </h2>

          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[560px] text-sm">
              <thead>
                <tr className="border-b border-line text-left text-muted">
                  <th className="py-2 font-medium">Opponent</th>
                  <th className="py-2 font-medium">Wager</th>
                  <th className="py-2 font-medium">Result</th>
                  <th className="py-2 font-medium">Payout</th>
                  <th className="py-2 font-medium">Date</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {matchesLoaded && matches.length === 0 && (
                  <tr>
                    <td colSpan={5} className="py-6 text-muted">
                      No matches yet.
                    </td>
                  </tr>
                )}
                {matches.map((m) => (
                  <MatchRow key={m.id} match={m} />
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </div>
  )
}

function MatchRow({ match }) {
  // 1v1 gives a name; team games give "N players" from the server.
  const opponent = match.opponent_username || '-'
  // `result` expected as 'W' | 'L' | null (pending). Fall back to status.
  const result = match.result ?? null
  const isWin = result === 'W' || result === 'win'
  const isLoss = result === 'L' || result === 'loss'

  return (
    <tr className="text-ink">
      <td className="py-3">{opponent}</td>
      <td className="py-3 text-muted">{money(match.wager_amount)}</td>
      <td className="py-3">
        {isWin ? (
          <span className="font-medium text-win">W</span>
        ) : isLoss ? (
          <span className="font-medium text-loss">L</span>
        ) : (
          <span className="text-muted">{match.status || '-'}</span>
        )}
      </td>
      <td className="py-3 text-muted">
        {match.payout != null ? money(match.payout) : '-'}
      </td>
      <td className="py-3 text-muted">{formatDate(match.created_at)}</td>
    </tr>
  )
}
