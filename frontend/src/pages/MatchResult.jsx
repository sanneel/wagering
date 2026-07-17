import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import client from '../api/client'
import Logo from '../components/Logo'
import InlineError from '../components/InlineError'
import { useAuth } from '../context/AuthContext'
import { money } from '../lib/format'

export default function MatchResult() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const [match, setMatch] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    client
      .get(`/match/${id}`)
      .then(({ data }) => {
        if (active) setMatch(data)
      })
      .catch(() => {
        if (active) setError('Could not load result.')
      })
    return () => {
      active = false
    }
  }, [id])

  if (error) {
    return (
      <Shell>
        <InlineError message={error} />
      </Shell>
    )
  }
  if (!match) {
    return (
      <Shell>
        <p className="text-center text-sm text-steel-500">Loading result…</p>
      </Shell>
    )
  }

  const size = match.team_size ?? 1
  const wager = parseFloat(match.wager_amount) || 0
  const pot = parseFloat(match.pot_amount) || wager * size * 2
  // No `||` fallback here: with zero rake, rake_amount is a legitimate "0.00"
  // and a falsy-fallback would resurrect a phantom 10% cut on every result.
  const rake = parseFloat(match.rake_amount ?? 0) || 0
  const payout = pot - rake

  // The winning side comes from winning_team; everything is framed around
  // whether the viewer was on it. Payouts follow FUNDING, not headcount — a
  // sponsor took a bigger share than a free-rider — so each seat's amount is
  // its contributed fraction of the side's buy-in.
  const won = match.winning_team
  const winners = match.seats.filter((s) => s.team === won)
  const losers = match.seats.filter((s) => s.team !== won)
  const sideTotal = winners.reduce((t, s) => t + (parseFloat(s.contributed) || 0), 0)
  const shareOf = (s) =>
    sideTotal > 0 ? (payout * (parseFloat(s.contributed) || 0)) / sideTotal : 0
  const mySeat = match.seats.find((s) => s.player.id === user?.id)
  const iWon = mySeat && mySeat.team === won
  // LEADER-mode party seats banked their winnings to the Team Balance instead
  // of a personal payout — say so rather than claiming money landed.
  const banked = (s) => s.party_split === 'LEADER'

  return (
    <Shell>
      <div className="text-center">
        <div className="font-display text-xs font-bold uppercase tracking-[0.3em] text-steel-500">
          {size}v{size} settled
        </div>
        {mySeat ? (
          <>
            <h1
              className={`mt-3 font-display text-6xl font-black uppercase italic leading-none ${
                iWon ? 'text-accent' : 'text-steel-400'
              }`}
            >
              {iWon ? 'You won' : 'You lost'}
            </h1>
            <div
              className={`mt-3 font-display text-3xl font-bold ${
                iWon ? 'text-white' : 'text-steel-500'
              }`}
            >
              {iWon
                ? `+${money(shareOf(mySeat))}`
                : `−${money(parseFloat(mySeat.contributed) || 0)}`}
            </div>
            {iWon && banked(mySeat) && (
              <p className="mt-2 text-xs uppercase tracking-[0.2em] text-steel-500">
                banked to your team balance
              </p>
            )}
          </>
        ) : (
          <h1 className="mt-3 font-display text-5xl font-black uppercase italic leading-none text-white">
            Team {won} took it
          </h1>
        )}
      </div>

      <div className="mt-10 grid gap-4 lg:grid-cols-2">
        <Side
          title={`Team ${won} winners`}
          seats={winners}
          meId={user?.id}
          tone="win"
          amountFor={(s) => `+${money(shareOf(s))}${banked(s) ? ' ⇒ pool' : ''}`}
        />
        <Side
          title={`Team ${won === 'A' ? 'B' : 'A'}`}
          seats={losers}
          meId={user?.id}
          tone="loss"
          amountFor={(s) => `−${money(parseFloat(s.contributed) || 0)}`}
        />
      </div>

      <p className="mt-6 text-center text-xs text-steel-500">
        Pot {money(pot)}
        {rake > 0 ? ` · rake ${money(rake)}` : ' · zero rake'} ·{' '}
        {money(payout)} paid out
        {size > 1 ? ', split by stake' : ''}
      </p>

      <div className="mt-8 flex items-center justify-center gap-3">
        <button
          type="button"
          onClick={() => navigate('/tables')}
          className="rounded-md bg-accent px-6 py-3 text-xs font-semibold uppercase tracking-wide text-white transition-colors hover:bg-accent-dark"
        >
          Back to tables
        </button>
        <button
          type="button"
          onClick={() => navigate('/wallet')}
          className="rounded-md border border-line-dark px-6 py-3 text-xs font-semibold uppercase tracking-wide text-steel-100 transition-colors hover:border-accent hover:text-accent"
        >
          Withdraw
        </button>
      </div>
    </Shell>
  )
}

function Side({ title, seats, meId, tone, amountFor }) {
  const win = tone === 'win'
  return (
    <div
      className={`rounded-xl border p-5 ${
        win ? 'border-accent/40 bg-accent/[0.06]' : 'border-line-dark bg-graphite-900'
      }`}
    >
      <div
        className={`mb-4 text-[10px] font-medium uppercase tracking-[0.24em] ${
          win ? 'text-accent' : 'text-steel-500'
        }`}
      >
        {title}
      </div>
      <div className="space-y-2">
        {seats.map((s) => (
          <div
            key={s.player.id}
            className="flex items-center justify-between gap-3 rounded-lg border border-line-dark bg-graphite-800 px-3 py-2.5"
          >
            <span className="truncate text-sm text-steel-100">
              {s.player.faceit_username}
              {s.player.id === meId && (
                <span className="ml-2 text-[10px] uppercase tracking-wide text-accent">
                  you
                </span>
              )}
            </span>
            <span
              className={`shrink-0 text-xs font-semibold ${
                win ? 'text-accent' : 'text-steel-500'
              }`}
            >
              {amountFor(s)}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

function Shell({ children }) {
  return (
    <div className="min-h-screen bg-graphite-950 text-steel-100">
      <header className="border-b border-line-dark">
        <div className="mx-auto flex h-16 max-w-5xl items-center px-6">
          <Logo to="/tables" light />
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-6 py-12">{children}</main>
    </div>
  )
}
