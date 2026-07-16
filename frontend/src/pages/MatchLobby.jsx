import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import client from '../api/client'
import Logo from '../components/Logo'
import InlineError from '../components/InlineError'
import { useAuth } from '../context/AuthContext'
import { money, errMsg } from '../lib/format'

const STATUS_TEXT = {
  PENDING: 'Waiting on seats',
  LOCKED: 'Table locked — launch CS2 and connect',
  LIVE: 'Match in progress',
  CANCELLED: 'Table cancelled — stakes refunded',
}

const POLL_MS = 3000

export default function MatchLobby() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { user, fetchMe } = useAuth()
  const [match, setMatch] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')
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
        err?.response?.status === 404 ? 'Table not found.' : 'Could not load table.'
      )
      return null
    }
  }, [id, navigate])

  // Poll until FINISHED (which redirects away) — seats fill while you watch.
  useEffect(() => {
    load()
    timerRef.current = setInterval(load, POLL_MS)
    return () => clearInterval(timerRef.current)
  }, [load])

  async function leave() {
    setBusy('leave')
    setError('')
    try {
      await client.post(`/tables/${id}/leave`)
      await fetchMe()
      navigate('/tables')
    } catch (err) {
      setError(errMsg(err, 'Could not leave the table.'))
      setBusy('')
    }
  }

  async function cancel() {
    setBusy('cancel')
    setError('')
    try {
      await client.delete(`/match/${id}/cancel`)
      await fetchMe()
      navigate('/tables')
    } catch (err) {
      setError(errMsg(err, 'Could not cancel the table.'))
      setBusy('')
    }
  }

  const size = match?.team_size ?? 1
  const a = match?.seats?.filter((s) => s.team === 'A') ?? []
  const b = match?.seats?.filter((s) => s.team === 'B') ?? []
  const isCreator = match?.creator_id === user?.id
  const seated = match?.seats?.some((s) => s.player.id === user?.id)
  const pending = match?.status === 'PENDING'

  return (
    <div className="min-h-screen bg-graphite-950 text-steel-100">
      <header className="border-b border-line-dark">
        <div className="mx-auto flex h-16 max-w-5xl items-center justify-between px-6">
          <Logo to="/tables" light />
          <button
            type="button"
            onClick={() => navigate('/tables')}
            className="text-xs uppercase tracking-[0.2em] text-steel-500 transition-colors hover:text-steel-100"
          >
            All tables
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-6 py-12">
        {!match && !error && (
          <p className="text-center text-sm text-steel-500">Loading table…</p>
        )}
        {error && (
          <div className="mb-6 text-center">
            <InlineError message={error} />
          </div>
        )}

        {match && (
          <>
            <div className="text-center">
              <div className="font-display text-5xl font-black italic leading-none text-accent">
                {size}v{size}
              </div>
              <p className="mt-3 text-sm font-medium text-steel-100">
                {STATUS_TEXT[match.status] || match.status}
              </p>
              {pending && (
                <p className="mt-1 text-xs text-steel-500">
                  {match.open_seats} of {match.seats_total} seats still open
                </p>
              )}
            </div>

            <div className="mt-10 grid gap-4 lg:grid-cols-[1fr_auto_1fr]">
              <Roster team="A" seats={a} size={size} meId={user?.id} />

              <div className="flex flex-col items-center justify-center px-4">
                <div className="text-[10px] uppercase tracking-[0.24em] text-steel-500">
                  Pot
                </div>
                <div className="mt-1 font-display text-4xl font-black italic leading-none text-white">
                  {money(
                    parseFloat(match.pot_amount) ||
                      parseFloat(match.wager_amount) * size * 2
                  )}
                </div>
                <div className="mt-2 font-display text-xs font-bold uppercase text-steel-500">
                  vs
                </div>
                <div className="mt-2 text-center text-[11px] text-steel-500">
                  {money(match.wager_amount)} a seat
                </div>
              </div>

              <Roster team="B" seats={b} size={size} meId={user?.id} />
            </div>

            <div className="mt-10 flex justify-center gap-3">
              {pending && seated && !isCreator && (
                <button
                  type="button"
                  onClick={leave}
                  disabled={!!busy}
                  className="rounded-md border border-line-dark px-5 py-2.5 text-xs font-semibold uppercase tracking-wide text-steel-100 transition-colors hover:border-loss hover:text-loss disabled:opacity-40"
                >
                  {busy === 'leave' ? 'Leaving…' : 'Leave table'}
                </button>
              )}
              {pending && isCreator && (
                <button
                  type="button"
                  onClick={cancel}
                  disabled={!!busy}
                  className="rounded-md border border-line-dark px-5 py-2.5 text-xs font-semibold uppercase tracking-wide text-steel-100 transition-colors hover:border-loss hover:text-loss disabled:opacity-40"
                >
                  {busy === 'cancel' ? 'Cancelling…' : 'Cancel table'}
                </button>
              )}
            </div>
            {pending && (
              <p className="mt-4 text-center text-[11px] text-steel-500">
                {isCreator
                  ? 'Cancelling refunds every stake at the table.'
                  : 'Leaving refunds your stake — you can do this until the table fills.'}
              </p>
            )}
          </>
        )}
      </main>
    </div>
  )
}

// One side. Empty seats render as dashed placeholders so a filling 5v5 shows
// exactly how many are still needed.
function Roster({ team, seats, size, meId }) {
  return (
    <div className="rounded-xl border border-line-dark bg-graphite-900 p-5">
      <div className="mb-4 text-[10px] font-medium uppercase tracking-[0.24em] text-steel-500">
        Team {team}
      </div>
      <div className="space-y-2">
        {Array.from({ length: size }).map((_, i) => {
          const s = seats[i]
          if (!s) {
            return (
              <div
                key={i}
                className="flex h-12 items-center justify-center rounded-lg border border-dashed border-line-dark text-[11px] uppercase tracking-widest text-steel-500"
              >
                Open seat
              </div>
            )
          }
          const p = s.player
          const me = p.id === meId
          return (
            <div
              key={i}
              className={`flex h-12 items-center gap-3 rounded-lg border px-3 ${
                me ? 'border-accent/50 bg-accent/10' : 'border-line-dark bg-graphite-800'
              }`}
            >
              <Avatar player={p} />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium text-steel-100">
                  {p.faceit_username}
                  {me && (
                    <span className="ml-2 text-[10px] uppercase tracking-wide text-accent">
                      you
                    </span>
                  )}
                </div>
              </div>
              {p.faceit_elo != null && (
                <div className="shrink-0 text-[11px] text-steel-500">
                  {p.faceit_elo}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function Avatar({ player }) {
  const name = player?.faceit_username || '?'
  const src = player?.avatar
  return (
    <div className="h-7 w-7 shrink-0 overflow-hidden rounded-full border border-line-dark bg-graphite-950">
      {src ? (
        <img
          src={src}
          alt={name}
          className="h-full w-full object-cover"
          onError={(e) => {
            e.currentTarget.style.display = 'none'
          }}
        />
      ) : (
        <div className="flex h-full w-full items-center justify-center text-[10px] font-semibold text-steel-500">
          {name.slice(0, 1).toUpperCase()}
        </div>
      )}
    </div>
  )
}
