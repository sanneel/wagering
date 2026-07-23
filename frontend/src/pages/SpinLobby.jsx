import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import client from '../api/client'
import Logo from '../components/Logo'
import InlineError from '../components/InlineError'
import Wheel from '../components/Wheel'
import { useAuth } from '../context/AuthContext'
import { money, errMsg } from '../lib/format'

const POLL_MS = 3000

// FACEIT hosts each 1v1 in a match room; a game carries its id once created.
const faceitRoom = (id) => `https://www.faceit.com/en/cs2/room/${id}`

const STATUS_TEXT = {
  PENDING: 'Waiting on entrants',
  LOCKED: 'Bracket set — spinning the wheel',
  LIVE: 'Bracket in progress',
  FINISHED: 'Bracket complete',
  CANCELLED: 'SpinCounter cancelled. Entries refunded',
}

// Round label from the round number and the bracket's total rounds: the last
// round is the final, the one before it the semifinal, and so on.
function roundLabel(round, total) {
  const fromEnd = total - round
  if (fromEnd === 0) return 'Final'
  if (fromEnd === 1) return 'Semifinal'
  if (fromEnd === 2) return 'Quarterfinal'
  return `Round ${round}`
}

export default function SpinLobby() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { user, fetchMe } = useAuth()
  const [t, setT] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')
  const [wheelDone, setWheelDone] = useState(false)
  const timerRef = useRef(null)
  const configRef = useRef(null)

  const load = useCallback(async () => {
    try {
      const { data } = await client.get(`/spincounter/${id}`)
      setT(data)
      setError('')
      return data
    } catch (err) {
      setError(
        err?.response?.status === 404
          ? 'SpinCounter not found.'
          : err?.response?.status === 403
            ? 'This bracket is private once it locks.'
            : 'Could not load the bracket.'
      )
      return null
    }
  }, [id])

  useEffect(() => {
    // The wheel needs the segment list; config is public and static.
    client
      .get('/spincounter/config')
      .then(({ data }) => {
        configRef.current = data
      })
      .catch(() => {})
    load()
    timerRef.current = setInterval(load, POLL_MS)
    return () => clearInterval(timerRef.current)
  }, [load])

  async function leave() {
    setBusy('leave')
    setError('')
    try {
      await client.post(`/spincounter/${id}/leave`)
      await fetchMe()
      navigate('/spincounter')
    } catch (err) {
      setError(errMsg(err, 'Could not leave.'))
      setBusy('')
    }
  }

  async function cancel() {
    setBusy('cancel')
    setError('')
    try {
      await client.delete(`/spincounter/${id}/cancel`)
      await fetchMe()
      navigate('/spincounter')
    } catch (err) {
      setError(errMsg(err, 'Could not cancel.'))
      setBusy('')
    }
  }

  const meId = user?.id
  const pending = t?.status === 'PENDING'
  const locked = t && ['LOCKED', 'LIVE', 'FINISHED'].includes(t.status)
  const isCreator = t?.creator_id === meId
  const joined = t?.joined
  // Refetch my balance once the wheel settles / a champion is crowned, so the
  // header reflects any payout without a manual reload.
  const finished = t?.status === 'FINISHED'
  useEffect(() => {
    if (finished || (locked && wheelDone)) fetchMe()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [finished, wheelDone])

  const wheelSegments = configRef.current?.wheel ?? []
  const showWheelSpin = locked && t.wheel_segment_index != null && wheelSegments.length > 0

  const rounds = useMemo(() => {
    if (!t) return []
    const byRound = {}
    for (const g of t.games) {
      ;(byRound[g.round] ||= []).push(g)
    }
    return Object.keys(byRound)
      .map(Number)
      .sort((a, b) => a - b)
      .map((r) => ({ round: r, games: byRound[r].sort((a, b) => a.slot - b.slot) }))
  }, [t])

  // The current player's live game (if any) drives the FACEIT call to action.
  const myLiveGame = useMemo(() => {
    if (!t || !meId) return null
    return (
      t.games.find(
        (g) =>
          g.status === 'LIVE' &&
          (g.player_a?.id === meId || g.player_b?.id === meId)
      ) || null
    )
  }, [t, meId])
  // Am I still alive in the bracket (seated, not eliminated, no champion yet)?
  const myEntry = t?.entries?.find((e) => e.player.id === meId)
  const stillIn = joined && myEntry && !myEntry.eliminated && !finished

  return (
    <div className="min-h-screen bg-graphite-950 text-steel-100">
      <header className="border-b border-line-dark">
        <div className="mx-auto flex h-16 max-w-5xl items-center justify-between px-6">
          <Logo to="/spincounter" light />
          <div className="flex items-center gap-4">
            <div className="text-right">
              <div className="text-[10px] uppercase tracking-[0.24em] text-steel-500">
                Balance
              </div>
              <div className="font-display text-base font-semibold leading-none text-white">
                {user ? money(user.balance) : '-'}
              </div>
            </div>
            <button
              type="button"
              onClick={() => navigate('/spincounter')}
              className="text-xs uppercase tracking-[0.2em] text-steel-500 transition-colors hover:text-steel-100"
            >
              All brackets
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6 py-12">
        {!t && !error && (
          <p className="text-center text-sm text-steel-500">Loading bracket…</p>
        )}
        {error && (
          <div className="mb-6 text-center">
            <InlineError message={error} />
          </div>
        )}

        {t && (
          <>
            <div className="text-center">
              <p className="text-[10px] font-medium uppercase tracking-[0.3em] text-accent">
                {t.size}-player SpinCounter
              </p>
              <h1 className="mt-2 font-display text-4xl font-black uppercase italic leading-none tracking-tight text-white">
                {money(t.prize_pool || parseFloat(t.entry_fee) * t.size)} pool
              </h1>
              <p className="mt-3 text-sm font-medium text-steel-100">
                {STATUS_TEXT[t.status] || t.status}
              </p>
              {pending && (
                <p className="mt-1 text-xs text-steel-500">
                  {t.open_seats} of {t.size} seats still open · {money(t.entry_fee)}{' '}
                  entry
                </p>
              )}
            </div>

            {/* ── Wheel of Fortune ── */}
            {showWheelSpin && (
              <div className="mt-10 flex flex-col items-center">
                <Wheel
                  segments={wheelSegments}
                  landOn={t.wheel_segment_index}
                  onSettle={() => setWheelDone(true)}
                />
                <WheelResult t={t} meId={meId} revealed={wheelDone} />
              </div>
            )}

            {/* ── Your live match: the FACEIT call to action ── */}
            {myLiveGame && (
              <div className="live-pulse mx-auto mt-10 max-w-xl rounded-xl border border-accent/50 bg-accent/10 p-5">
                <div className="flex flex-col items-center gap-4 sm:flex-row sm:justify-between">
                  <div className="text-center sm:text-left">
                    <div className="flex items-center justify-center gap-2 sm:justify-start">
                      <span className="relative flex h-2 w-2">
                        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent opacity-75" />
                        <span className="relative inline-flex h-2 w-2 rounded-full bg-accent" />
                      </span>
                      <span className="text-[10px] font-semibold uppercase tracking-[0.24em] text-accent">
                        Your match is live
                      </span>
                    </div>
                    <div className="mt-1.5 font-display text-xl font-bold italic text-white">
                      {myLiveGame.player_a?.faceit_username} vs{' '}
                      {myLiveGame.player_b?.faceit_username}
                    </div>
                    <div className="mt-0.5 text-[11px] text-steel-400">
                      {roundLabel(myLiveGame.round, t.rounds_total)} · best of{' '}
                      {t.rounds_best_of}
                    </div>
                  </div>
                  {myLiveGame.faceit_match_id ? (
                    <a
                      href={faceitRoom(myLiveGame.faceit_match_id)}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="shrink-0 rounded-md bg-accent px-6 py-3 text-xs font-semibold uppercase tracking-wide text-white transition-colors hover:bg-accent-dark"
                    >
                      Open FACEIT room
                    </a>
                  ) : (
                    <span className="shrink-0 rounded-md border border-line-dark px-6 py-3 text-xs font-semibold uppercase tracking-wide text-steel-400">
                      Setting up match…
                    </span>
                  )}
                </div>
              </div>
            )}

            {/* ── Still in it, waiting on another match ── */}
            {stillIn && !myLiveGame && locked && (
              <p className="mt-8 text-center text-sm text-steel-400">
                You&apos;re through — waiting on the other match to set your next
                opponent.
              </p>
            )}

            {/* ── Champion banner ── */}
            {finished && t.champion && (
              <div className="mx-auto mt-10 max-w-md rounded-xl border border-accent/40 bg-accent/10 p-6 text-center">
                <div className="text-[10px] uppercase tracking-[0.24em] text-accent">
                  Champion
                </div>
                <div className="mt-1 font-display text-3xl font-black italic text-white">
                  {t.champion.faceit_username}
                  {t.champion.id === meId && (
                    <span className="ml-2 text-sm not-italic text-accent">you</span>
                  )}
                </div>
                <div className="mt-1 text-sm text-steel-300">
                  takes the {money(t.prize_pool)} pool
                </div>
              </div>
            )}

            {/* ── Bracket ── */}
            {locked && rounds.length > 0 && (
              <div className="mt-12">
                <h2 className="mb-5 text-[10px] font-medium uppercase tracking-[0.28em] text-steel-500">
                  Bracket
                </h2>
                <div className="overflow-x-auto pb-2">
                  <div className="flex min-w-max gap-10">
                    {rounds.map(({ round, games }) => (
                      <div key={round} className="spin-col min-w-[15rem] flex-1">
                        <div className="mb-3 text-center text-[10px] font-semibold uppercase tracking-[0.2em] text-steel-500">
                          {roundLabel(round, t.rounds_total)}
                        </div>
                        <div className="spin-round h-[calc(100%-1.5rem)]">
                          {games.map((g) => (
                            <div key={g.id} className="spin-match">
                              <GameCard g={g} meId={meId} />
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                    {/* Champion node caps the bracket. */}
                    <div className="spin-col flex min-w-[11rem] flex-col">
                      <div className="mb-3 text-center text-[10px] font-semibold uppercase tracking-[0.2em] text-steel-500">
                        Champion
                      </div>
                      <div className="spin-round h-[calc(100%-1.5rem)]">
                        <div className="spin-match">
                          <div
                            className={`flex h-full min-h-[5rem] flex-col items-center justify-center rounded-lg border p-4 text-center ${
                              t.champion
                                ? 'border-accent/50 bg-accent/10'
                                : 'border-dashed border-line-dark'
                            }`}
                          >
                            <span className="text-2xl">🏆</span>
                            <span
                              className={`mt-1 font-display text-sm font-bold italic ${
                                t.champion ? 'text-white' : 'text-steel-600'
                              }`}
                            >
                              {t.champion ? t.champion.faceit_username : 'TBD'}
                            </span>
                            {t.champion && (
                              <span className="mt-0.5 text-[10px] text-accent">
                                {money(t.prize_pool)}
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* ── Entrants (while filling) ── */}
            {pending && (
              <div className="mx-auto mt-10 max-w-xl">
                <h2 className="mb-4 text-center text-[10px] font-medium uppercase tracking-[0.28em] text-steel-500">
                  Entrants
                </h2>
                <div className="space-y-2">
                  {Array.from({ length: t.size }).map((_, i) => {
                    const e = t.entries[i]
                    if (!e) {
                      return (
                        <div
                          key={i}
                          className="flex h-12 items-center justify-center rounded-lg border border-dashed border-line-dark text-[11px] uppercase tracking-widest text-steel-500"
                        >
                          Open seat
                        </div>
                      )
                    }
                    const me = e.player.id === meId
                    return (
                      <div
                        key={i}
                        className={`flex h-12 items-center gap-3 rounded-lg border px-4 ${
                          me
                            ? 'border-accent/50 bg-accent/10'
                            : 'border-line-dark bg-graphite-900'
                        }`}
                      >
                        <span className="font-display text-sm font-bold text-steel-500">
                          {i + 1}
                        </span>
                        <span className="truncate text-sm font-medium text-steel-100">
                          {e.player.faceit_username}
                          {me && (
                            <span className="ml-2 text-[10px] uppercase tracking-wide text-accent">
                              you
                            </span>
                          )}
                        </span>
                        <span className="ml-auto text-[11px] text-steel-500">
                          {e.player.faceit_elo}
                        </span>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {/* ── Actions ── */}
            <div className="mt-10 flex justify-center gap-3">
              {pending && joined && !isCreator && (
                <button
                  type="button"
                  onClick={leave}
                  disabled={!!busy}
                  className="rounded-md border border-line-dark px-5 py-2.5 text-xs font-semibold uppercase tracking-wide text-steel-100 transition-colors hover:border-loss hover:text-loss disabled:opacity-40"
                >
                  {busy === 'leave' ? 'Leaving…' : 'Leave bracket'}
                </button>
              )}
              {pending && isCreator && (
                <button
                  type="button"
                  onClick={cancel}
                  disabled={!!busy}
                  className="rounded-md border border-line-dark px-5 py-2.5 text-xs font-semibold uppercase tracking-wide text-steel-100 transition-colors hover:border-loss hover:text-loss disabled:opacity-40"
                >
                  {busy === 'cancel' ? 'Cancelling…' : 'Cancel bracket'}
                </button>
              )}
              {(finished || t.status === 'CANCELLED') && (
                <button
                  type="button"
                  onClick={() => navigate('/spincounter')}
                  className="rounded-md bg-accent px-6 py-2.5 text-xs font-semibold uppercase tracking-wide text-white transition-colors hover:bg-accent-dark"
                >
                  Back to brackets
                </button>
              )}
            </div>
            {pending && (
              <p className="mt-4 text-center text-[11px] text-steel-500">
                {isCreator
                  ? 'Cancelling refunds every entry.'
                  : joined
                    ? 'Leaving refunds your entry. Once the bracket fills, the wheel spins and there is no leaving.'
                    : 'Enter from the brackets list to take a seat.'}
              </p>
            )}
          </>
        )}
      </main>
    </div>
  )
}

function WheelResult({ t, meId, revealed }) {
  if (!revealed) {
    return (
      <p className="mt-6 animate-pulse text-sm font-medium uppercase tracking-[0.2em] text-steel-400">
        Spinning…
      </p>
    )
  }
  const won = t.wheel_winner
  const mine = won?.id === meId
  return (
    <div className="mt-6 text-center">
      <div className="text-[10px] uppercase tracking-[0.24em] text-steel-500">
        Wheel of Fortune
      </div>
      <div className="mt-1 font-display text-2xl font-black italic text-white">
        {money(t.wheel_prize)} to {won ? won.faceit_username : '—'}
        {mine && <span className="ml-2 text-sm not-italic text-accent">you</span>}
      </div>
      <p className="mt-1 text-[11px] text-steel-500">
        A house jackpot on top of the prize pool — now play the bracket.
      </p>
    </div>
  )
}

function GameCard({ g, meId }) {
  const live = g.status === 'LIVE'
  const done = g.status === 'FINISHED'
  return (
    <div
      className={`rounded-lg border p-3 ${
        live ? 'border-accent/40 bg-graphite-900' : 'border-line-dark bg-graphite-900'
      }`}
    >
      <Player
        player={g.player_a}
        score={g.score_a}
        won={done && g.winner_id === g.player_a?.id}
        lost={done && g.winner_id && g.winner_id !== g.player_a?.id}
        meId={meId}
      />
      <div className="my-1 flex items-center gap-2">
        <div className="h-px flex-1 bg-line-dark" />
        <span className="text-[9px] font-bold uppercase tracking-widest text-steel-500">
          {live ? 'live' : 'vs'}
        </span>
        <div className="h-px flex-1 bg-line-dark" />
      </div>
      <Player
        player={g.player_b}
        score={g.score_b}
        won={done && g.winner_id === g.player_b?.id}
        lost={done && g.winner_id && g.winner_id !== g.player_b?.id}
        meId={meId}
      />
    </div>
  )
}

function Player({ player, score, won, lost, meId }) {
  const me = player && player.id === meId
  return (
    <div
      className={`flex items-center gap-2 rounded px-2 py-1.5 ${
        won ? 'bg-accent/10' : ''
      }`}
    >
      <span
        className={`min-w-0 flex-1 truncate text-sm ${
          !player
            ? 'italic text-steel-600'
            : won
              ? 'font-semibold text-white'
              : lost
                ? 'text-steel-500 line-through'
                : 'text-steel-100'
        }`}
      >
        {player ? player.faceit_username : 'TBD'}
        {me && <span className="ml-1.5 text-[10px] uppercase text-accent">you</span>}
      </span>
      <span
        className={`font-display text-sm font-bold ${
          won ? 'text-accent' : 'text-steel-500'
        }`}
      >
        {player ? score : '–'}
      </span>
    </div>
  )
}
