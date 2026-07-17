import { useCallback, useEffect, useRef, useState } from 'react'
import client from '../api/client'
import { money, errMsg } from '../lib/format'

// The party strip that sits above the tables: member cards with the leader
// crowned, empty "+" slots that hand out the invite link, the pooled Team
// Balance with its movement log on hover, and the split-mode toggle. The
// toggle is deliberately visible to every member — a leader quietly flipping
// to "Leader decides" is exactly what members need to be able to see.
const POLL_MS = 5000

export default function PartyWidget({ user, onParty }) {
  const [party, setParty] = useState(null)
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')
  const [copied, setCopied] = useState(false)
  const [fundAmt, setFundAmt] = useState('')
  const [payTarget, setPayTarget] = useState(null) // member being paid
  const [payAmt, setPayAmt] = useState('')

  const apply = useCallback(
    (p) => {
      setParty(p)
      onParty?.(p)
    },
    [onParty]
  )

  const load = useCallback(async () => {
    try {
      const { data } = await client.get('/party')
      apply(data || null)
    } catch {
      /* keep last state; transient errors shouldn't dissolve the widget */
    } finally {
      setLoaded(true)
    }
  }, [apply])

  useEffect(() => {
    load()
    const t = setInterval(load, POLL_MS)
    return () => clearInterval(t)
  }, [load])

  async function act(name, fn) {
    setError('')
    setBusy(name)
    try {
      await fn()
    } catch (err) {
      setError(errMsg(err, 'Something went wrong.'))
    } finally {
      setBusy('')
    }
  }

  const isLeader = party && party.leader_id === user?.id
  const size = party?.members?.length ?? 1
  const emptySlots = Math.max(0, (party?.max_size ?? 5) - size)

  async function createAndInvite() {
    await act('create', async () => {
      const { data } = await client.post('/party')
      apply(data)
      copyInvite(data.invite_code)
    })
  }

  function copyInvite(code) {
    const url = `${window.location.origin}/tables?party=${code}`
    navigator.clipboard?.writeText(url).catch(() => {})
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  async function leave() {
    await act('leave', async () => {
      await client.post('/party/leave')
      apply(null)
    })
  }

  async function kick(uid) {
    await act(`kick-${uid}`, async () => {
      const { data } = await client.post(`/party/kick/${uid}`)
      apply(data)
    })
  }

  async function toggleSplit() {
    if (!isLeader) return
    await act('split', async () => {
      const next =
        party.split_mode === 'PROPORTIONAL' ? 'LEADER' : 'PROPORTIONAL'
      const { data } = await client.post('/party/split-mode', {
        split_mode: next,
      })
      apply(data)
    })
  }

  async function contribute() {
    const amount = parseFloat(fundAmt)
    if (!amount || amount <= 0) return setError('Enter a valid amount.')
    await act('fund', async () => {
      const { data } = await client.post('/party/contribute', { amount })
      apply(data)
      setFundAmt('')
    })
  }

  async function payout() {
    const amount = parseFloat(payAmt)
    if (!amount || amount <= 0) return setError('Enter a valid amount.')
    await act('pay', async () => {
      const { data } = await client.post('/party/distribute', {
        user_id: payTarget,
        amount,
      })
      apply(data)
      setPayTarget(null)
      setPayAmt('')
    })
  }

  if (!loaded) return null

  return (
    <section className="mt-8 rounded-xl border border-line-dark bg-graphite-900">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line-dark px-5 py-3">
        <div className="flex items-center gap-3">
          <h2 className="font-display text-lg font-bold uppercase italic tracking-tight text-white">
            Party
          </h2>
          {party && (
            <span className="text-xs text-steel-500">
              {size}/{party.max_size}
            </span>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {party && <TeamBalance party={party} />}
          {party && (
            <SplitToggle
              mode={party.split_mode}
              canEdit={isLeader}
              busy={busy === 'split'}
              onToggle={toggleSplit}
            />
          )}
          {party && (
            <button
              type="button"
              onClick={leave}
              disabled={!!busy}
              className="rounded-md border border-line-dark px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-steel-400 transition-colors hover:border-loss hover:text-loss disabled:opacity-40"
            >
              {isLeader ? 'Disband' : 'Leave'}
            </button>
          )}
        </div>
      </div>

      {/* Members strip. Solo shows the user card plus a single Invite tile
          (one CTA, not four empty seats — small screens couldn't fit them and
          they never carried more meaning than the one). Once in a party the
          strip lists every member and a single Invite tile that says how
          many seats remain. */}
      <div className="flex flex-wrap items-stretch gap-2 p-4 sm:gap-3 sm:p-5">
        {(party?.members ?? [{ player: user, is_leader: true, entitlement: 0 }])
          .filter((m) => m.player)
          .map((m) => (
            <MemberCard
              key={m.player.id}
              member={m}
              me={user?.id}
              isLeader={!!party && isLeader}
              inParty={!!party}
              busy={busy}
              onKick={() => kick(m.player.id)}
              onPay={() => {
                setPayTarget(m.player.id)
                setPayAmt('')
              }}
            />
          ))}

        {(!party || emptySlots > 0) && (
          <button
            type="button"
            onClick={() =>
              party ? copyInvite(party.invite_code) : createAndInvite()
            }
            disabled={busy === 'create'}
            title={party ? 'Copy invite link' : 'Create a party & copy the invite link'}
            className="flex min-h-[6.5rem] flex-1 flex-col items-center justify-center rounded-lg border border-dashed border-line-dark px-3 text-steel-500 transition-colors hover:border-accent hover:text-accent disabled:opacity-40 sm:min-h-[7.5rem] sm:min-w-[6rem] sm:flex-none"
          >
            <span className="text-3xl font-light leading-none">+</span>
            <span className="mt-2 px-1 text-center text-[9px] uppercase tracking-widest">
              {copied
                ? 'Link copied'
                : party
                  ? `Invite (${emptySlots})`
                  : 'Create & invite'}
            </span>
          </button>
        )}
      </div>

      {/* Pool controls: anyone funds; the leader can pay members out. */}
      {party && (
        <div className="flex flex-wrap items-center gap-3 border-t border-line-dark px-5 py-3">
          <div className="flex items-center rounded-md border border-line-dark bg-graphite-800 px-2">
            <span className="text-xs text-steel-500">$</span>
            <input
              type="number"
              min="1"
              step="1"
              value={fundAmt}
              placeholder="Amount"
              onChange={(e) => setFundAmt(e.target.value)}
              className="w-20 bg-transparent px-2 py-1.5 text-xs text-white outline-none placeholder:text-steel-500"
            />
          </div>
          <button
            type="button"
            onClick={contribute}
            disabled={!!busy}
            className="rounded-md bg-accent px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-white transition-colors hover:bg-accent-dark disabled:opacity-40"
          >
            {busy === 'fund' ? '…' : 'Add to team balance'}
          </button>
          <span className="text-[10px] text-steel-500">
            Uneven funding is fine. Payouts follow who funded what.
          </span>
          {error && <span className="text-xs text-loss">{error}</span>}
        </div>
      )}

      {/* Leader payout dialog — capped server-side at the member's share;
          anything above it comes out of the leader's own share and carries a
          wagering requirement to the recipient. */}
      {party && payTarget != null && (
        <div className="flex flex-wrap items-center gap-3 border-t border-line-dark bg-graphite-950 px-5 py-3">
          <span className="text-xs text-steel-400">
            Pay{' '}
            <span className="font-semibold text-white">
              {
                party.members.find((m) => m.player.id === payTarget)?.player
                  .faceit_username
              }
            </span>
          </span>
          <div className="flex items-center rounded-md border border-line-dark bg-graphite-800 px-2">
            <span className="text-xs text-steel-500">$</span>
            <input
              type="number"
              min="0.01"
              step="0.01"
              value={payAmt}
              autoFocus
              placeholder="Amount"
              onChange={(e) => setPayAmt(e.target.value)}
              className="w-20 bg-transparent px-2 py-1.5 text-xs text-white outline-none placeholder:text-steel-500"
            />
          </div>
          <button
            type="button"
            onClick={payout}
            disabled={!!busy}
            className="rounded-md bg-accent px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-white hover:bg-accent-dark disabled:opacity-40"
          >
            {busy === 'pay' ? '…' : 'Pay out'}
          </button>
          <button
            type="button"
            onClick={() => setPayTarget(null)}
            className="text-[11px] uppercase tracking-wide text-steel-500 hover:text-steel-100"
          >
            Cancel
          </button>
          <span className="text-[10px] text-steel-500">
            Above their share comes out of yours, and must be wagered before
            it can be withdrawn.
          </span>
        </div>
      )}
    </section>
  )
}

function MemberCard({ member, me, isLeader, inParty, busy, onKick, onPay }) {
  const p = member.player
  const name = p.faceit_username || 'you'
  const mine = p.id === me
  return (
    <div
      className={`relative flex min-h-[7.5rem] w-28 flex-col items-center justify-center rounded-lg border px-2 py-3 ${
        mine ? 'border-accent/50 bg-accent/[0.07]' : 'border-line-dark bg-graphite-800'
      }`}
    >
      {member.is_leader && (
        <svg
          className="absolute -top-2 left-1/2 -translate-x-1/2"
          width="18"
          height="12"
          viewBox="0 0 18 12"
          aria-label="party leader"
        >
          <path d="M1 11h16L15 3l-4 3-2-5-2 5-4-3z" fill="#E8B10A" />
        </svg>
      )}
      <div className="h-10 w-10 overflow-hidden rounded-full border border-line-dark bg-graphite-950">
        {p.avatar ? (
          <img
            src={p.avatar}
            alt={name}
            className="h-full w-full object-cover"
            onError={(e) => {
              e.currentTarget.style.display = 'none'
            }}
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-xs font-semibold text-steel-500">
            {name.slice(0, 1).toUpperCase()}
          </div>
        )}
      </div>
      <div className="mt-2 max-w-full truncate text-xs font-medium text-steel-100">
        {name}
      </div>
      {inParty && (
        <div
          className="mt-0.5 text-[10px] text-steel-500"
          title="This member's share of the team balance"
        >
          {money(member.entitlement)}
        </div>
      )}
      {inParty && isLeader && !member.is_leader && (
        <div className="mt-1.5 flex gap-1.5">
          <button
            type="button"
            onClick={onPay}
            className="rounded border border-line-dark px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-steel-400 hover:border-accent hover:text-accent"
          >
            Pay
          </button>
          <button
            type="button"
            onClick={onKick}
            disabled={!!busy}
            className="rounded border border-line-dark px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-steel-400 hover:border-loss hover:text-loss disabled:opacity-40"
          >
            Kick
          </button>
        </div>
      )}
      {inParty && isLeader && member.is_leader && (
        <button
          type="button"
          onClick={onPay}
          className="mt-1.5 rounded border border-line-dark px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-steel-400 hover:border-accent hover:text-accent"
        >
          Pay self
        </button>
      )}
    </div>
  )
}

// The Team Balance chip — hover reveals every pool movement, so any member
// can audit who funded, what the pool spent, and where payouts went.
function TeamBalance({ party }) {
  return (
    <div className="group relative">
      <div className="flex cursor-default items-center gap-2 rounded-full border border-line-dark bg-graphite-950 px-3 py-1.5">
        <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
          <circle cx="7" cy="7" r="6" fill="none" stroke="#E8B10A" strokeWidth="1.6" />
          <path d="M7 3.5v7M4.8 5.4h3.4a1.3 1.3 0 010 2.6H5.8a1.3 1.3 0 000 2.6h3.4" stroke="#E8B10A" strokeWidth="1.1" fill="none" />
        </svg>
        <span className="text-[10px] uppercase tracking-[0.18em] text-steel-500">
          Team balance
        </span>
        <span className="font-display text-sm font-bold text-white">
          {money(party.pool_balance)}
        </span>
      </div>

      <div className="invisible absolute right-0 top-full z-30 mt-2 w-72 rounded-lg border border-line-dark bg-graphite-950 p-3 opacity-0 shadow-xl transition-opacity group-hover:visible group-hover:opacity-100">
        <div className="mb-2 text-[10px] uppercase tracking-[0.2em] text-steel-500">
          Pool activity
        </div>
        {party.logs.length === 0 && (
          <p className="text-xs text-steel-500">No activity yet.</p>
        )}
        <div className="max-h-48 space-y-1 overflow-y-auto">
          {party.logs.map((l, i) => (
            <div key={i} className="flex items-center justify-between text-xs">
              <span className="truncate text-steel-400">
                <LogVerb kind={l.kind} /> {l.username}
              </span>
              <span
                className={
                  ['CONTRIBUTE', 'WIN', 'REFUND'].includes(l.kind)
                    ? 'shrink-0 font-medium text-win'
                    : 'shrink-0 font-medium text-steel-100'
                }
              >
                {['CONTRIBUTE', 'WIN', 'REFUND'].includes(l.kind) ? '+' : '−'}
                {money(l.amount)}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function LogVerb({ kind }) {
  const verbs = {
    CONTRIBUTE: 'funded by',
    RECLAIM: 'reclaimed by',
    ESCROW: 'staked for',
    REFUND: 'refunded for',
    WIN: 'won for',
    PAYOUT: 'paid to',
  }
  return <span>{verbs[kind] || kind}</span>
}

// FACEIT-style pill toggle. Members see the live setting; only the leader can
// flip it, and every queued match snapshots it — so what you saw when you
// readied up is what settles.
function SplitToggle({ mode, canEdit, busy, onToggle }) {
  const proportional = mode === 'PROPORTIONAL'
  return (
    <button
      type="button"
      onClick={onToggle}
      disabled={!canEdit || busy}
      title={
        canEdit
          ? 'How winnings are divided'
          : 'Only the leader can change this. You can always see it'
      }
      className={`flex items-center gap-2 rounded-full border px-3 py-1.5 transition-colors ${
        proportional
          ? 'border-line-dark bg-graphite-950'
          : 'border-accent/60 bg-accent/10'
      } ${canEdit ? 'cursor-pointer hover:border-steel-500' : 'cursor-default'}`}
    >
      <span
        className={`text-[10px] font-semibold uppercase tracking-[0.14em] ${
          proportional ? 'text-steel-400' : 'text-accent'
        }`}
      >
        {proportional ? 'Proportional split' : 'Leader decides'}
      </span>
      <span
        className={`relative h-4 w-8 rounded-full transition-colors ${
          proportional ? 'bg-graphite-800' : 'bg-accent'
        }`}
      >
        <span
          className={`absolute top-0.5 h-3 w-3 rounded-full bg-white transition-all ${
            proportional ? 'left-0.5' : 'left-[1.125rem]'
          }`}
        />
      </span>
    </button>
  )
}
