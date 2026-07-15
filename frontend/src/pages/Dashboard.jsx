import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import client from '../api/client'
import TopNav from '../components/TopNav'
import InlineError from '../components/InlineError'
import { money, formatDate } from '../lib/format'

const PRESETS = [5, 10, 25, 50]

export default function Dashboard() {
  const navigate = useNavigate()
  const [selected, setSelected] = useState(5)
  const [custom, setCustom] = useState('')
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')

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

  const wagerAmount =
    selected === 'custom' ? parseFloat(custom) : selected

  async function findOpponent() {
    setError('')
    if (!wagerAmount || wagerAmount <= 0) {
      setError('Enter a valid wager amount.')
      return
    }
    setCreating(true)
    try {
      const { data } = await client.post('/match/create', {
        wager_amount: wagerAmount,
      })
      navigate(`/match/${data.id}`)
    } catch (err) {
      setError(
        err?.response?.data?.detail
          ? String(err.response.data.detail)
          : 'Could not create match.'
      )
      setCreating(false)
    }
  }

  return (
    <div className="min-h-screen">
      <TopNav />

      <main className="mx-auto max-w-5xl px-4 py-10">
        {/* Wager selector */}
        <section>
          <h1 className="text-xl font-semibold text-ink">New match</h1>
          <p className="mt-1 text-sm text-muted">
            Pick a wager. We&apos;ll match you with an opponent at the same
            stake.
          </p>

          <div className="mt-5 flex flex-wrap items-center gap-2">
            {PRESETS.map((amt) => (
              <button
                key={amt}
                type="button"
                onClick={() => {
                  setSelected(amt)
                  setError('')
                }}
                className={`rounded-md border px-4 py-2 text-sm font-medium ${
                  selected === amt
                    ? 'border-accent bg-accent text-white'
                    : 'border-line bg-white text-ink hover:border-ink'
                }`}
              >
                {money(amt)}
              </button>
            ))}

            <div
              className={`flex items-center rounded-md border px-3 ${
                selected === 'custom' ? 'border-accent' : 'border-line'
              }`}
            >
              <span className="text-sm text-muted">$</span>
              <input
                type="number"
                min="1"
                step="1"
                value={custom}
                placeholder="Custom"
                onFocus={() => setSelected('custom')}
                onChange={(e) => {
                  setCustom(e.target.value)
                  setSelected('custom')
                  setError('')
                }}
                className="w-24 bg-transparent px-2 py-2 text-sm text-ink outline-none placeholder:text-muted"
              />
            </div>
          </div>

          <div className="mt-6 flex items-center gap-4">
            <button
              type="button"
              onClick={findOpponent}
              disabled={creating}
              className="rounded-md bg-accent px-5 py-2.5 text-sm font-medium text-white hover:bg-accent-dark disabled:opacity-60"
            >
              {creating ? 'Finding…' : 'Find Opponent'}
            </button>
            <InlineError message={error} />
          </div>
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
  const opponent =
    match.opponent_username ||
    match.opponent?.faceit_username ||
    '—'
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
          <span className="text-muted">{match.status || '—'}</span>
        )}
      </td>
      <td className="py-3 text-muted">
        {match.payout != null ? money(match.payout) : '—'}
      </td>
      <td className="py-3 text-muted">{formatDate(match.created_at)}</td>
    </tr>
  )
}
