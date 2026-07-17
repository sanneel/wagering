import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import client from '../api/client'
import Logo from '../components/Logo'
import InlineError from '../components/InlineError'
import PartyWidget from '../components/PartyWidget'
import { useAuth } from '../context/AuthContext'
import { money, errMsg } from '../lib/format'

const STAKES = [5, 10, 25, 50, 100]

// Copy per format. The server owns which formats exist (GET /formats, driven by
// ALLOWED_TEAM_SIZES); this only supplies the wording for the ones it returns,
// so adding 3v3 server-side needs one entry here and nothing else.
const FORMAT_COPY = {
  1: { blurb: 'Pure aim duel', detail: 'One life, one opponent, best of the map.' },
  2: { blurb: 'Grab a partner', detail: 'Two a side. Trade frags, split the pot.' },
  5: { blurb: 'Full squad', detail: 'Classic competitive. Ten players, one pot.' },
}

// Tables refresh on a slow poll — seats fill while you're looking at the list.
const POLL_MS = 4000

export default function Tables() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const { user, fetchMe } = useAuth()

  const [formats, setFormats] = useState([])
  const [filter, setFilter] = useState(null) // null = all formats
  const [tables, setTables] = useState([])
  const [loaded, setLoaded] = useState(false)

  const [openSize, setOpenSize] = useState(1)
  const [stake, setStake] = useState(10)
  const [customStake, setCustomStake] = useState('')
  const [creating, setCreating] = useState(false)
  const [joiningId, setJoiningId] = useState(null)
  const [error, setError] = useState('')

  // The caller's party, kept in sync by the widget. Everything below gates on
  // its size: which formats can be queued, what a queue costs, who may queue.
  const [party, setParty] = useState(null)
  const partySize = party?.members?.length ?? 1
  const isPartyLeader = !party || party.leader_id === user?.id

  // Invite links land here as /tables?party=CODE — join, then clean the URL
  // so a reload doesn't retry a spent invite.
  useEffect(() => {
    const code = params.get('party')
    if (!code) return
    client
      .post('/party/join', { invite_code: code })
      .catch(() => {})
      .finally(() => {
        params.delete('party')
        setParams(params, { replace: true })
      })
  }, [params, setParams])

  // A party must fit on one side, so shrinking formats drop out as it grows.
  // Snap the picker to a legal format instead of leaving a dead selection.
  useEffect(() => {
    if (openSize < partySize) {
      const legal = formats.find((f) => f.team_size >= partySize)
      if (legal) setOpenSize(legal.team_size)
    }
  }, [partySize, openSize, formats])

  useEffect(() => {
    client
      .get('/formats')
      .then(({ data }) => {
        const list = Array.isArray(data) ? data : []
        setFormats(list)
        if (list.length && !list.some((f) => f.team_size === 1)) {
          setOpenSize(list[0].team_size)
        }
      })
      .catch(() => setFormats([{ team_size: 1, label: '1v1' }]))
  }, [])

  const loadTables = useCallback(async () => {
    try {
      const { data } = await client.get('/tables', {
        params: filter ? { team_size: filter } : undefined,
      })
      setTables(Array.isArray(data) ? data : [])
    } catch {
      setTables([])
    } finally {
      setLoaded(true)
    }
  }, [filter])

  useEffect(() => {
    setLoaded(false)
    loadTables()
    const t = setInterval(loadTables, POLL_MS)
    return () => clearInterval(t)
  }, [loadTables])

  const wager = useMemo(
    () => (stake === 'custom' ? parseFloat(customStake) : stake),
    [stake, customStake]
  )

  async function openTable() {
    setError('')
    if (!wager || wager <= 0) return setError('Enter a valid stake.')
    setCreating(true)
    try {
      const { data } = await client.post('/tables', {
        wager_amount: wager,
        team_size: openSize,
      })
      await fetchMe()
      navigate(`/match/${data.id}`)
    } catch (err) {
      setError(errMsg(err, 'Could not open the table.'))
      setCreating(false)
    }
  }

  async function joinTable(id) {
    setError('')
    setJoiningId(id)
    try {
      await client.post(`/tables/${id}/join`)
      await fetchMe()
      navigate(`/match/${id}`)
    } catch (err) {
      setError(errMsg(err, 'Could not take a seat.'))
      setJoiningId(null)
      loadTables()
    }
  }

  const balance = parseFloat(user?.balance ?? 0)

  return (
    <div className="min-h-screen bg-graphite-950 text-steel-100">
      <header className="sticky top-0 z-40 border-b border-line-dark bg-graphite-950/90 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
          <Logo to="/dashboard" light />
          <div className="flex items-center gap-5">
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
        <div className="flex items-end justify-between gap-6">
          <div>
            <p className="text-[10px] font-medium uppercase tracking-[0.3em] text-accent">
              Live tables
            </p>
            <h1 className="mt-2 font-display text-5xl font-black uppercase italic leading-none tracking-tight text-white">
              Take a seat
            </h1>
            <p className="mt-3 max-w-md text-sm leading-relaxed text-steel-400">
              Every seat is one escrowed stake. A table locks the moment the
              last seat fills. Zero rake, winners take the whole pot.
            </p>
          </div>
        </div>

        {/* ── Party ── */}
        <PartyWidget user={user} onParty={setParty} />

        {/* ── Open a table ── */}
        <section className="mt-10 overflow-hidden rounded-xl border border-line-dark bg-graphite-900">
          <div className="border-b border-line-dark px-6 py-4">
            <h2 className="font-display text-xl font-bold uppercase italic tracking-tight text-white">
              Open a table
            </h2>
          </div>

          <div className="grid gap-8 p-6 lg:grid-cols-[1fr_auto]">
            <div className="space-y-6">
              <Field label="Format">
                <div className="flex flex-wrap gap-3">
                  {formats.map((f) => {
                    const copy = FORMAT_COPY[f.team_size] ?? {}
                    const on = openSize === f.team_size
                    // A party can only queue formats it fits into — a duo
                    // gets 2v2/5v5, a full five gets only 5v5.
                    const locked = f.team_size < partySize
                    return (
                      <button
                        key={f.team_size}
                        type="button"
                        disabled={locked}
                        onClick={() => setOpenSize(f.team_size)}
                        title={
                          locked
                            ? `Your party of ${partySize} doesn't fit in ${f.label}`
                            : undefined
                        }
                        className={`group relative min-w-[9.5rem] rounded-lg border px-4 py-3 text-left transition-colors ${
                          locked
                            ? 'cursor-not-allowed border-line-dark bg-graphite-900 opacity-40'
                            : on
                              ? 'border-accent bg-accent/10'
                              : 'border-line-dark bg-graphite-800 hover:border-steel-500'
                        }`}
                      >
                        <div
                          className={`font-display text-2xl font-black italic leading-none ${
                            on && !locked ? 'text-accent' : 'text-white'
                          }`}
                        >
                          {f.label}
                        </div>
                        <div className="mt-1 text-[11px] leading-tight text-steel-400">
                          {locked
                            ? `Needs a party of ≤${f.team_size}`
                            : copy.blurb ?? `${f.team_size} per side`}
                        </div>
                      </button>
                    )
                  })}
                </div>
                <p className="mt-2 text-xs text-steel-500">
                  {FORMAT_COPY[openSize]?.detail ??
                    `${openSize} players per side.`}
                </p>
              </Field>

              <Field label="Stake per player">
                <div className="flex flex-wrap items-center gap-2">
                  {STAKES.map((amt) => (
                    <button
                      key={amt}
                      type="button"
                      onClick={() => {
                        setStake(amt)
                        setError('')
                      }}
                      className={`rounded-md border px-4 py-2 text-sm font-semibold transition-colors ${
                        stake === amt
                          ? 'border-accent bg-accent text-white'
                          : 'border-line-dark bg-graphite-800 text-steel-100 hover:border-steel-500'
                      }`}
                    >
                      {money(amt)}
                    </button>
                  ))}
                  <div
                    className={`flex items-center rounded-md border bg-graphite-800 px-3 ${
                      stake === 'custom' ? 'border-accent' : 'border-line-dark'
                    }`}
                  >
                    <span className="text-sm text-steel-500">$</span>
                    <input
                      type="number"
                      min="1"
                      step="1"
                      value={customStake}
                      placeholder="Custom"
                      onFocus={() => setStake('custom')}
                      onChange={(e) => {
                        setCustomStake(e.target.value)
                        setStake('custom')
                        setError('')
                      }}
                      className="w-24 bg-transparent px-2 py-2 text-sm text-white outline-none placeholder:text-steel-500"
                    />
                  </div>
                </div>
              </Field>
            </div>

            {/* Stake maths, so nobody has to work out what they're committing. */}
            <aside className="w-full rounded-lg border border-line-dark bg-graphite-950 p-5 lg:w-64">
              <Summary
                teamSize={openSize}
                wager={wager}
                balance={balance}
                partySize={partySize}
                poolBalance={parseFloat(party?.pool_balance ?? 0)}
                isPartyLeader={isPartyLeader}
                busy={creating}
                onOpen={openTable}
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
              Open tables
            </h2>
            <div className="flex gap-2">
              <Chip on={filter === null} onClick={() => setFilter(null)}>
                All
              </Chip>
              {formats.map((f) => (
                <Chip
                  key={f.team_size}
                  on={filter === f.team_size}
                  onClick={() => setFilter(f.team_size)}
                >
                  {f.label}
                </Chip>
              ))}
            </div>
          </div>

          <div className="mt-5 space-y-3">
            {!loaded && <TableSkeleton />}
            {loaded && tables.length === 0 && (
              <EmptyTables
                onOpen={() => {
                  window.scrollTo({ top: 0, behavior: 'smooth' })
                }}
              />
            )}
            {loaded &&
              tables.map((t) => (
                <TableRow
                  key={t.id}
                  table={t}
                  meId={user?.id}
                  partySize={partySize}
                  canQueue={isPartyLeader}
                  busy={joiningId === t.id}
                  onJoin={() => joinTable(t.id)}
                  onWatch={() => navigate(`/match/${t.id}`)}
                />
              ))}
          </div>
        </section>
      </main>
    </div>
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

function Summary({
  teamSize,
  wager,
  balance,
  partySize,
  poolBalance,
  isPartyLeader,
  busy,
  onOpen,
}) {
  const valid = Number.isFinite(wager) && wager > 0
  const seats = teamSize * 2
  const pot = valid ? wager * seats : 0

  // Solo queues fund one seat from the personal balance; a party funds
  // party_size seats from the Team Balance, however unevenly it was filled.
  const asParty = partySize >= 2
  const buyIn = valid ? wager * (asParty ? partySize : 1) : 0
  const short = valid && (asParty ? poolBalance < buyIn : wager > balance)
  const notLeader = asParty && !isPartyLeader

  return (
    <>
      <div className="text-[10px] font-medium uppercase tracking-[0.24em] text-steel-500">
        {asParty ? `Party buy-in (${partySize} seats)` : 'You put in'}
      </div>
      <div className="mt-1 font-display text-4xl font-black italic leading-none text-white">
        {valid ? money(buyIn) : '-'}
      </div>
      {asParty && (
        <div className="mt-1 text-[10px] text-steel-500">
          from the team balance ({money(poolBalance)} available)
        </div>
      )}

      <dl className="mt-5 space-y-2 border-t border-line-dark pt-4 text-xs">
        <Line k="Seats" v={`${seats} (${teamSize} a side)`} />
        <Line k="Full pot" v={valid ? money(pot) : '-'} />
        <Line k="Rake" v="0%" />
      </dl>

      <div className="mt-4 rounded-md border border-accent/30 bg-accent/10 p-3">
        <div className="text-[10px] uppercase tracking-[0.2em] text-accent">
          Your side wins
        </div>
        <div className="mt-0.5 font-display text-2xl font-bold leading-none text-white">
          {valid ? money(pot) : '-'}
        </div>
        <div className="mt-1 text-[10px] text-steel-400">
          {asParty
            ? 'split by who funded what'
            : teamSize > 1
              ? 'split across your side by stake'
              : 'the whole pot'}
        </div>
      </div>

      <button
        type="button"
        onClick={onOpen}
        disabled={busy || !valid || short || notLeader}
        className="mt-5 w-full rounded-md bg-accent px-4 py-3 text-sm font-semibold uppercase tracking-wide text-white transition-colors hover:bg-accent-dark disabled:cursor-not-allowed disabled:opacity-40"
      >
        {busy
          ? 'Opening…'
          : notLeader
            ? 'Leader queues the party'
            : short
              ? asParty
                ? 'Team balance short'
                : 'Not enough balance'
              : asParty
                ? `Queue party of ${partySize}`
                : 'Open table'}
      </button>
      <p className="mt-2 text-center text-[10px] leading-relaxed text-steel-500">
        {asParty
          ? 'The buy-in leaves the team balance when the table opens; pulling out before it fills returns it.'
          : 'Your stake is escrowed when the table opens. Leave before it fills and you get it back.'}
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

function TableRow({ table, meId, partySize, canQueue, busy, onJoin, onWatch }) {
  const size = table.team_size
  const label = `${size}v${size}`
  const a = table.seats.filter((s) => s.team === 'A')
  const b = table.seats.filter((s) => s.team === 'B')
  const mine = table.joined || table.creator_id === meId
  const full = table.open_seats === 0
  // A party joins as a block on one side, so it needs that many free seats
  // together — a duo can't take the last seat of a 5v5.
  const fits =
    Math.max(size - a.length, size - b.length) >= partySize && canQueue

  const btnLabel = busy ? '…' : mine ? 'Open' : !fits && !full ? 'No room' : 'Join'
  const btnDisabled = busy || (!mine && (full || !fits))
  const btnTitle =
    !mine && !fits && !full
      ? canQueue
        ? `No side has ${partySize} seats free for your party`
        : 'Only your party leader can queue'
      : undefined
  const btnClass = mine
    ? 'border border-line-dark text-steel-100 hover:border-accent hover:text-accent'
    : 'bg-accent text-white hover:bg-accent-dark'

  return (
    <div className="group rounded-lg border border-line-dark bg-graphite-900 p-4 transition-colors hover:border-steel-500/60">
      {/* Header row: format, stake, pot, action. Same at every width — the
          numbers are what a scroller-through-the-list needs first. */}
      <div className="flex items-center gap-4">
        <div className="font-display text-2xl font-black italic leading-none text-accent">
          {label}
        </div>
        <div className="min-w-0">
          <div className="text-[10px] uppercase tracking-[0.18em] text-steel-500">
            Stake · Pot
          </div>
          <div className="flex items-baseline gap-2 font-display leading-none">
            <span className="text-base font-bold text-white sm:text-lg">
              {money(table.wager_amount)}
            </span>
            <span className="text-xs text-steel-500">/</span>
            <span className="text-base font-bold text-accent sm:text-lg">
              {money(parseFloat(table.wager_amount) * size * 2)}
            </span>
          </div>
        </div>
        <div className="ml-auto flex items-center gap-3">
          <span className="hidden text-xs text-steel-400 sm:inline">
            {full
              ? 'Filling…'
              : `${table.open_seats}/${table.seats_total} open`}
          </span>
          <button
            type="button"
            onClick={mine ? onWatch : onJoin}
            disabled={btnDisabled}
            title={btnTitle}
            className={`shrink-0 rounded-md px-4 py-2 text-xs font-semibold uppercase tracking-wide transition-colors disabled:cursor-not-allowed disabled:opacity-40 sm:px-5 sm:py-2.5 ${btnClass}`}
          >
            {btnLabel}
          </button>
        </div>
      </div>

      {/* Rosters. Sides sit side-by-side on desktop, one-per-line on tablet
          and phone — a 5v5 has ten pills, they cannot cohabit a phone row. */}
      <div className="mt-3 grid gap-2 md:grid-cols-[1fr_auto_1fr] md:items-center md:gap-3">
        <Side team="A" seats={a} size={size} />
        <span className="hidden font-display text-[10px] font-bold uppercase text-steel-500 md:inline">
          vs
        </span>
        <Side team="B" seats={b} size={size} />
      </div>

      {/* Seats-left footnote gets its own line on mobile so the header stays
          scannable. */}
      <div className="mt-2 text-[11px] text-steel-500 sm:hidden">
        {full ? 'Filling…' : `${table.open_seats} of ${table.seats_total} seats open`}
      </div>
    </div>
  )
}

// A side's seats: filled ones show the player, empty ones as gaps. Pills wrap
// when the side doesn't fit, so a 5v5 on a phone becomes two neat rows of
// pills rather than a horizontal overflow.
function Side({ team, seats, size }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="mr-1 font-display text-[10px] font-bold uppercase text-steel-500 md:hidden">
        {team}
      </span>
      {Array.from({ length: size }).map((_, i) => {
        const s = seats[i]
        return s ? (
          <span
            key={i}
            title={s.player.faceit_username}
            className="max-w-[7rem] truncate rounded border border-line-dark bg-graphite-800 px-2 py-1 text-[11px] text-steel-100"
          >
            {s.player.faceit_username}
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
  )
}

function TableSkeleton() {
  return (
    <>
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="h-[68px] animate-pulse rounded-lg border border-line-dark bg-graphite-900"
        />
      ))}
    </>
  )
}

function EmptyTables({ onOpen }) {
  return (
    <div className="rounded-lg border border-dashed border-line-dark bg-graphite-900/50 px-6 py-14 text-center">
      <p className="font-display text-2xl font-bold uppercase italic text-steel-100">
        No tables open
      </p>
      <p className="mx-auto mt-2 max-w-sm text-sm text-steel-400">
        Nobody&apos;s sitting yet. Open one and the first player at your stake
        takes the other seat.
      </p>
      <button
        type="button"
        onClick={onOpen}
        className="mt-5 rounded-md bg-accent px-6 py-2.5 text-xs font-semibold uppercase tracking-wide text-white transition-colors hover:bg-accent-dark"
      >
        Open a table
      </button>
    </div>
  )
}
