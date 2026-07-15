import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import client from '../api/client'
import Logo from '../components/Logo'
import PlayerCard from '../components/PlayerCard'
import InlineError from '../components/InlineError'
import { money } from '../lib/format'

const STATUS_TEXT = {
  PENDING: 'Waiting for opponent…',
  LOCKED: 'Match created — launch CS2 and connect',
  LIVE: 'Match in progress',
}

export default function MatchLobby() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [match, setMatch] = useState(null)
  const [error, setError] = useState('')
  const [cancelling, setCancelling] = useState(false)
  const timerRef = useRef(null)

  const load = useCallback(async () => {
    try {
      const { data } = await client.get(`/match/${id}`)
      setMatch(data)
      setError('')
      if (data.status === 'FINISHED') {
        navigate(`/match/${id}/result`, { replace: true })
      }
      return data
    } catch (err) {
      setError(
        err?.response?.status === 404
          ? 'Match not found.'
          : 'Could not load match.'
      )
      return null
    }
  }, [id, navigate])

  // Poll every 3 seconds until FINISHED (which redirects away).
  useEffect(() => {
    load()
    timerRef.current = setInterval(load, 3000)
    return () => clearInterval(timerRef.current)
  }, [load])

  async function cancelMatch() {
    setCancelling(true)
    setError('')
    try {
      await client.delete(`/match/${id}/cancel`)
      navigate('/dashboard')
    } catch (err) {
      setError(
        err?.response?.data?.detail
          ? String(err.response.data.detail)
          : 'Could not cancel match.'
      )
      setCancelling(false)
    }
  }

  const statusText = match ? STATUS_TEXT[match.status] || match.status : ''

  return (
    <div className="min-h-screen">
      <header className="border-b border-line">
        <div className="mx-auto flex h-14 max-w-5xl items-center px-4">
          <Logo to="/dashboard" />
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 py-12">
        {!match && !error && (
          <p className="text-center text-sm text-muted">Loading match…</p>
        )}

        {error && (
          <div className="mb-6 text-center">
            <InlineError message={error} />
          </div>
        )}

        {match && (
          <>
            <div className="flex items-stretch gap-4">
              <PlayerCard player={match.player1} />

              <div className="flex min-w-[110px] flex-col items-center justify-center">
                <div className="text-xs uppercase tracking-wide text-muted">
                  Pot
                </div>
                <div className="mt-1 text-3xl font-semibold text-ink sm:text-4xl">
                  {money(match.pot_amount || (match.wager_amount || 0) * 2)}
                </div>
                <div className="mt-1 text-xs text-muted">vs</div>
              </div>

              <PlayerCard player={match.player2} />
            </div>

            <div className="mt-8 text-center">
              <p className="text-sm font-medium text-ink">{statusText}</p>

              {match.status === 'PENDING' && (
                <button
                  type="button"
                  onClick={cancelMatch}
                  disabled={cancelling}
                  className="mt-4 rounded-md border border-line px-4 py-2 text-sm font-medium text-ink hover:border-loss hover:text-loss disabled:opacity-60"
                >
                  {cancelling ? 'Cancelling…' : 'Cancel match'}
                </button>
              )}
            </div>
          </>
        )}
      </main>
    </div>
  )
}
