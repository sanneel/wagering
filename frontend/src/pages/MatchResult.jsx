import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import client from '../api/client'
import Logo from '../components/Logo'
import PlayerCard from '../components/PlayerCard'
import InlineError from '../components/InlineError'
import { money } from '../lib/format'

export default function MatchResult() {
  const { id } = useParams()
  const navigate = useNavigate()
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
        <p className="text-center text-sm text-muted">Loading result…</p>
      </Shell>
    )
  }

  const wager = parseFloat(match.wager_amount) || 0
  const pot = parseFloat(match.pot_amount) || wager * 2
  const rake = parseFloat(match.rake_amount) || pot * 0.1
  const payout = pot - rake

  // Map winner_id to player1/player2.
  const p1Won = match.winner_id != null && match.winner_id === match.player1_id
  const winner = p1Won ? match.player1 : match.player2
  const loser = p1Won ? match.player2 : match.player1

  return (
    <Shell>
      <div className="flex items-stretch gap-4">
        <PlayerCard player={winner} border="win" payout={payout} />
        <PlayerCard player={loser} border="loss" payout={wager} />
      </div>

      <p className="mt-6 text-center text-sm text-muted">
        Platform fee: {money(rake)} (10%)
      </p>

      <div className="mt-8 flex items-center justify-center gap-3">
        <button
          type="button"
          onClick={() => navigate('/dashboard')}
          className="rounded-md bg-accent px-5 py-2.5 text-sm font-medium text-white hover:bg-accent-dark"
        >
          Play Again
        </button>
        <button
          type="button"
          onClick={() => navigate('/wallet')}
          className="rounded-md border border-line px-5 py-2.5 text-sm font-medium text-ink hover:border-ink"
        >
          Withdraw
        </button>
      </div>
    </Shell>
  )
}

function Shell({ children }) {
  return (
    <div className="min-h-screen">
      <header className="border-b border-line">
        <div className="mx-auto flex h-14 max-w-5xl items-center px-4">
          <Logo to="/dashboard" />
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-4 py-12">{children}</main>
    </div>
  )
}
