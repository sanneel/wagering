import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import client from '../api/client'
import Logo from '../components/Logo'
import InlineError from '../components/InlineError'
import Wheel from '../components/Wheel'
import { useAuth } from '../context/AuthContext'
import { money, errMsg } from '../lib/format'

const ENTRIES = [3, 5, 10, 25, 50]

// Copy per bracket size. The server owns which sizes exist (GET
// /spincounter/config, driven by SPIN_SIZES); this only supplies the wording.
const SIZE_COPY = {
  2: { blurb: 'Head to head', detail: 'Straight to the final. One 1v1, best of three.' },
  4: { blurb: 'Semis + final', detail: 'Four enter. Win your semi, then take the final.' },
  8: { blurb: 'Full bracket', detail: 'Eight enter. Quarters, semis, final — one champion.' },
}

const POLL_MS = 4000

export default function SpinCounter() {
  const navigate = useNavigate()
  const { user, fetchMe } = useAuth()

  const [config, setConfig] = useState(null)
  const [filter, setFilter] = useState(null) // null = all sizes
  const [tournaments, setTournaments] = useState([])
  const [loaded, setLoaded] = useState(false)

  const [openSize, setOpenSize] = useState(4)
  const [entry, setEntry] = useState(3)
  const [customEntry, setCustomEntry] = useState('')
  const [creating, setCreating] = useState(false)
  const [joiningId, setJoiningId] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    client
      .get('/spincounter/config')
      .then(({ data }) => {
        setConfig(data)
        if (Array.isArray(data.sizes) && !data.sizes.includes(4)) {
          setOpenSize(data.sizes[0])
        }
      })
      .catch(() => setConfig({ sizes: [2, 4, 8], wheel: [] }))
  }, [])

  const loadList = useCallback(async () => {
    try {
      const { data } = await client.get('/spincounter', {
        params: filter ? { size: filter } : undefined,
      })
      setTournaments(Array.isArray(data) ? data : [])
    } catch {
      setTournaments([])
    } finally {
      setLoaded(true)
    }
  }, [filter])

  useEffect(() => {
    setLoaded(false)
    loadList()
    const t = setInterval(loadList, POLL_MS)
    return () => clearInterval(t)
  }, [loadList])

  const fee = useMemo(
    () => (entry === 'custom' ? parseFloat(customEntry) : entry),
    [entry, customEntry]
  )

  async function openTournament() {
    setError('')
    if (!fee || fee <= 0) return setError('Enter a valid entry fee.')
    setCreating(true)
    try {
      const { data } = await client.post('/spincounter', {
        entry_fee: fee,
        size: openSize,
      })
      await fetchMe()
      navigate(`/spincounter/${data.id}`)
    } catch (err) {
      setError(errMsg(err, 'Could not open the SpinCounter.'))
      setCreating(false)
    }
  }

  async function join(id) {
    setError('')
    setJoiningId(id)
    try {
      await client.post(`/spincounter/${id}/join`)
      await fetchMe()
      navigate(`/spincounter/${id}`)
    } catch (err) {
      setError(errMsg(err, 'Could not enter.'))
      setJoiningId(null)
      loadList()
    }
  }

  const balance = parseFloat(user?.balance ?? 0)
  const sizes = config?.sizes ?? [2, 4, 8]
  const wheel = config?.wheel ?? []
  const topPrize = wheel.reduce((m, s) => Math.max(m, parseFloat(s.amount)), 0)

  return (
    <div className="min-h-screen bg-graphite-950 text-steel-100">
      <header className="sticky top-0 z-40 border-b border-line-dark bg-graphite-950/90 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
          <Logo to="/dashboard" light />
          <div className="flex items-center gap-5">
            <button
              type="button"
              onClick={() => navigate('/tables')}
              className="text-xs font-semibold uppercase tracking-wide text-steel-400 transition-colors hover:text-steel-100"
            >
              Tables
            </button>
            <div className="text-right">
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
              className="rounded-md border border-line-dark px-4 py-2 text-xs font-semibold uppercase tracking-wide text-steel-100 transition-colors hover:border-accent hover:text-accent"
            >
              Deposit
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 pb-24 pt-10">
        <div className="grid gap-8 lg:grid-cols-[1fr_auto] lg:items-center">
          <div>
            <p className="text-[10px] font-medium uppercase tracking-[0.3em] text-accent">
              SpinCounter
            </p>
            <h1 className="mt-2 font-display text-5xl font-black uppercase italic leading-none tracking-tight text-white">
              Spin, then counter
            </h1>
            <p className="mt-3 max-w-md text-sm leading-relaxed text-steel-400">
              A 1v1 knockout bracket. Everyone pays the same entry. The moment
              the bracket fills, the Wheel of Fortune spins and drops a jackpot
              on one lucky entrant — then you fight through the bracket for the
              prize pool. Two ways to win, one buy-in.
            </p>
            <div className="mt-5 flex flex-wrap gap-3 text-xs">
              <Badge>Wheel up to {money(topPrize)}</Badge>
              <Badge>Best of {config?.rounds_best_of ?? 3}</Badge>
              <Badge>Winner takes the pool</Badge>
            </div>
          </div>
          <div className="w-full max-w-[18rem] justify-self-center">
            {wheel.length > 0 && <Wheel segments={wheel} />}
          </div>
        </div>

        {/* ── Open a SpinCounter ── */}
        <section className="mt-12 overflow-hidden rounded-xl border border-line-dark bg-graphite-900">
          <div className="border-b border-line-dark px-6 py-4">
            <h2 className="font-display text-xl font-bold uppercase italic tracking-tight text-white">
              Open a SpinCounter
            </h2>
          </div>

          <div className="grid gap-8 p-6 lg:grid-cols-[1fr_auto]">
            <div className="space-y-6">
              <Field label="Bracket">
                <div className="flex flex-wrap gap-3">
                  {sizes.map((n) => {
                    const copy = SIZE_COPY[n] ?? {}
                    const on = openSize === n
                    return (
                      <button
                        key={n}
                        type="button"
                        onClick={() => setOpenSize(n)}
                        className={`group relative min-w-[9.5rem] rounded-lg border px-4 py-3 text-left transition-colors ${
                          on
                            ? 'border-accent bg-accent/10'
                            : 'border-line-dark bg-graphite-800 hover:border-steel-500'
                        }`}
                      >
                        <div
                          className={`font-display text-2xl font-black italic leading-none ${
                            on ? 'text-accent' : 'text-white'
                          }`}
                        >
                          {n} players
                        </div>
                        <div className="mt-1 text-[11px] leading-tight text-steel-400">
                          {copy.blurb ?? `${n}-player knockout`}
                        </div>
                      </button>
                    )
                  })}
                </div>
                <p className="mt-2 text-xs text-steel-500">
                  {SIZE_COPY[openSize]?.detail ?? `${openSize}-player knockout bracket.`}
                </p>
              </Field>

              <Field label="Entry fee">
                <div className="flex flex-wrap items-center gap-2">
                  {ENTRIES.map((amt) => (
                    <button
                      key={amt}
                      type="button"
                      onClick={() => {
                        setEntry(amt)
                        setError('')
                      }}
                      className={`rounded-md border px-4 py-2 text-sm font-semibold transition-colors ${
                        entry === amt
                          ? 'border-accent bg-accent text-white'
                          : 'border-line-dark bg-graphite-800 text-steel-100 hover:border-steel-500'
                      }`}
                    >
                      {money(amt)}
                    </button>
                  ))}
                  <div
                    className={`flex items-center rounded-md border bg-graphite-800 px-3 ${
                      entry === 'custom' ? 'border-accent' : 'border-line-dark'
                    }`}
                  >
                    <span className="text-sm text-steel-500">$</span>
                    <input
                      type="number"
                      min="1"
                      step="1"
                      value={customEntry}
                      placeholder="Custom"
                      onFocus={() => setEntry('custom')}
                      onChange={(e) => {
                        setCustomEntry(e.target.value)
                        setEntry('custom')
                        setError('')
                      }}
                      className="w-24 bg-transparent px-2 py-2 text-sm text-white outline-none placeholder:text-steel-500"
                    />
                  </div>
                </div>
              </Field>
            </div>

            <aside className="w-full rounded-lg border border-line-dark bg-graphite-950 p-5 lg:w-64">
              <Summary
                size={openSize}
                fee={fee}
                balance={balance}
                topPrize={topPrize}
                busy={creating}
                onOpen={openTournament}
              />
            </aside>
          </div>
          {error && (
            <div className="border-t border-line-dark px-6 py-3">
              <InlineError message={error} />
            </div>
          )}
        </section>

        {/* ── Browse ── */}
        <section className="mt-14">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <h2 className="font-display text-xl font-bold uppercase italic tracking-tight text-white">
              Open brackets
            </h2>
            <div className="flex gap-2">
              <Chip on={filter === null} onClick={() => setFilter(null)}>
                All
              </Chip>
              {sizes.map((n) => (
                <Chip key={n} on={filter === n} onClick={() => setFilter(n)}>
                  {n}-player
                </Chip>
              ))}
            </div>
          </div>

          <div className="mt-5 space-y-3">
            {!loaded && <RowSkeleton />}
            {loaded && tournaments.length === 0 && (
              <EmptyState
                onOpen={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
              />
            )}
            {loaded &&
              tournaments.map((t) => (
                <TournamentRow
                  key={t.id}
                  t={t}
                  meId={user?.id}
                  busy={joiningId === t.id}
                  onJoin={() => join(t.id)}
                  onWatch={() => navigate(`/spincounter/${t.id}`)}
                />
              ))}
          </div>
        </section>
      </main>
    </div>
  )
}

function Badge({ children }) {
  return (
    <span className="rounded-full border border-line-dark bg-graphite-900 px-3 py-1.5 font-semibold uppercase tracking-wide text-steel-300">
      {children}
    </span>
  )
}

function Field({ label, children }) {
  return (
    <div>
      <div className="mb-3 text-[10px] font-medium uppercase tracking-[0.24em] text-steel-500">
        {label}
      </div>
      {children}
    </div>
  )
}

function Chip({ on, onClick, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full border px-4 py-1.5 text-xs font-semibold uppercase tracking-wide transition-colors ${
        on
          ? 'border-accent bg-accent text-white'
          : 'border-line-dark text-steel-400 hover:border-steel-500 hover:text-steel-100'
      }`}
    >
      {children}
    </button>
  )
}

function Summary({ size, fee, balance, topPrize, busy, onOpen }) {
  const valid = Number.isFinite(fee) && fee > 0
  const pool = valid ? fee * size : 0
  const short = valid && fee > balance

  return (
    <>
      <div className="text-[10px] font-medium uppercase tracking-[0.24em] text-steel-500">
        You put in
      </div>
      <div className="mt-1 font-display text-4xl font-black italic leading-none text-white">
        {valid ? money(fee) : '-'}
      </div>

      <dl className="mt-5 space-y-2 border-t border-line-dark pt-4 text-xs">
        <Line k="Bracket" v={`${size} players`} />
        <Line k="Prize pool" v={valid ? money(pool) : '-'} />
        <Line k="Rake" v="0%" />
      </dl>

      <div className="mt-4 rounded-md border border-accent/30 bg-accent/10 p-3">
        <div className="text-[10px] uppercase tracking-[0.2em] text-accent">
          Champion takes
        </div>
        <div className="mt-0.5 font-display text-2xl font-bold leading-none text-white">
          {valid ? money(pool) : '-'}
        </div>
        <div className="mt-1 text-[10px] text-steel-400">
          plus a wheel jackpot up to {money(topPrize)} for one lucky entrant
        </div>
      </div>

      <button
        type="button"
        onClick={onOpen}
        disabled={busy || !valid || short}
        className="mt-5 w-full rounded-md bg-accent px-4 py-3 text-sm font-semibold uppercase tracking-wide text-white transition-colors hover:bg-accent-dark disabled:cursor-not-allowed disabled:opacity-40"
      >
        {busy ? 'Opening…' : short ? 'Not enough balance' : 'Open bracket'}
      </button>
      <p className="mt-2 text-center text-[10px] leading-relaxed text-steel-500">
        Your entry is escrowed when the bracket opens. Leave before it fills and
        you get it back.
      </p>
    </>
  )
}

function Line({ k, v }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-steel-500">{k}</dt>
      <dd className="font-medium text-steel-100">{v}</dd>
    </div>
  )
}

function TournamentRow({ t, meId, busy, onJoin, onWatch }) {
  const mine = t.joined || t.creator_id === meId
  const full = t.open_seats === 0
  const pool = parseFloat(t.entry_fee) * t.size

  const btnLabel = busy ? '…' : mine ? 'Open' : full ? 'Full' : 'Enter'
  const btnDisabled = busy || (!mine && full)
  const btnClass = mine
    ? 'border border-line-dark text-steel-100 hover:border-accent hover:text-accent'
    : 'bg-accent text-white hover:bg-accent-dark'

  return (
    <div className="group rounded-lg border border-line-dark bg-graphite-900 p-4 transition-colors hover:border-steel-500/60">
      <div className="flex items-center gap-4">
        <div className="font-display text-2xl font-black italic leading-none text-accent">
          {t.size}P
        </div>
        <div className="min-w-0">
          <div className="text-[10px] uppercase tracking-[0.18em] text-steel-500">
            Entry · Pool
          </div>
          <div className="flex items-baseline gap-2 font-display leading-none">
            <span className="text-base font-bold text-white sm:text-lg">
              {money(t.entry_fee)}
            </span>
            <span className="text-xs text-steel-500">/</span>
            <span className="text-base font-bold text-accent sm:text-lg">
              {money(pool)}
            </span>
          </div>
        </div>
        <div className="ml-auto flex items-center gap-3">
          <span className="hidden text-xs text-steel-400 sm:inline">
            {full ? 'Filling…' : `${t.open_seats}/${t.size} open`}
          </span>
          <button
            type="button"
            onClick={mine ? onWatch : onJoin}
            disabled={btnDisabled}
            className={`shrink-0 rounded-md px-4 py-2 text-xs font-semibold uppercase tracking-wide transition-colors disabled:cursor-not-allowed disabled:opacity-40 sm:px-5 sm:py-2.5 ${btnClass}`}
          >
            {btnLabel}
          </button>
        </div>
      </div>

      {/* Entrant pills — one per bracket seat, filled or empty. */}
      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {Array.from({ length: t.size }).map((_, i) => {
          const e = t.entries[i]
          return e ? (
            <span
              key={i}
              title={e.player.faceit_username}
              className="max-w-[7rem] truncate rounded border border-line-dark bg-graphite-800 px-2 py-1 text-[11px] text-steel-100"
            >
              {e.player.faceit_username}
            </span>
          ) : (
            <span
              key={i}
              className="h-6 w-8 rounded border border-dashed border-line-dark"
              aria-label="empty seat"
            />
          )
        })}
      </div>

      <div className="mt-2 text-[11px] text-steel-500 sm:hidden">
        {full ? 'Filling…' : `${t.open_seats} of ${t.size} seats open`}
      </div>
    </div>
  )
}

function RowSkeleton() {
  return (
    <>
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="h-[92px] animate-pulse rounded-lg border border-line-dark bg-graphite-900"
        />
      ))}
    </>
  )
}

function EmptyState({ onOpen }) {
  return (
    <div className="rounded-lg border border-dashed border-line-dark bg-graphite-900/50 px-6 py-14 text-center">
      <p className="font-display text-2xl font-bold uppercase italic text-steel-100">
        No brackets open
      </p>
      <p className="mx-auto mt-2 max-w-sm text-sm text-steel-400">
        Nobody&apos;s spinning yet. Open a bracket and the wheel drops the moment
        it fills.
      </p>
      <button
        type="button"
        onClick={onOpen}
        className="mt-5 rounded-md bg-accent px-6 py-2.5 text-xs font-semibold uppercase tracking-wide text-white transition-colors hover:bg-accent-dark"
      >
        Open a SpinCounter
      </button>
    </div>
  )
}
