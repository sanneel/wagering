import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import client from '../api/client'
import Logo from '../components/Logo'
import InlineError from '../components/InlineError'
import { useAuth } from '../context/AuthContext'
import { money, formatDate, errMsg } from '../lib/format'

export default function Wallet() {
  const { user, fetchMe } = useAuth()
  const navigate = useNavigate()

  const [depositAmt, setDepositAmt] = useState('')
  const [withdrawAmt, setWithdrawAmt] = useState('')
  const [depositErr, setDepositErr] = useState('')
  const [withdrawErr, setWithdrawErr] = useState('')
  const [depositBusy, setDepositBusy] = useState(false)
  const [withdrawBusy, setWithdrawBusy] = useState(false)
  const [notice, setNotice] = useState('')

  const [txns, setTxns] = useState([])
  const [txnsLoaded, setTxnsLoaded] = useState(false)

  const [rewards, setRewards] = useState(null)
  const [claiming, setClaiming] = useState(false)
  const [limitInput, setLimitInput] = useState('')
  const [rgBusy, setRgBusy] = useState('')
  const [rgNotice, setRgNotice] = useState('')

  // Live quote for the amount in the withdraw box, so the fee and the
  // rollover gate are visible before the user commits.
  const [quote, setQuote] = useState(null)
  const quoteReq = useRef(0)

  const rollover = parseFloat(user?.rollover_requirement ?? 0)

  useEffect(() => {
    const amount = parseFloat(withdrawAmt)
    if (!amount || amount <= 0) {
      setQuote(null)
      return
    }
    const seq = ++quoteReq.current
    const t = setTimeout(async () => {
      try {
        const { data } = await client.get('/wallet/quote', { params: { amount } })
        if (seq === quoteReq.current) setQuote(data)
      } catch {
        if (seq === quoteReq.current) setQuote(null)
      }
    }, 300)
    return () => clearTimeout(t)
  }, [withdrawAmt])

  async function loadTxns() {
    try {
      const { data } = await client.get('/wallet/transactions')
      setTxns(Array.isArray(data) ? data : [])
    } catch {
      setTxns([])
    } finally {
      setTxnsLoaded(true)
    }
  }

  async function loadRewards() {
    try {
      const { data } = await client.get('/me/rewards')
      setRewards(data)
    } catch {
      setRewards(null)
    }
  }

  useEffect(() => {
    loadTxns()
    loadRewards()
  }, [])

  async function claimDaily() {
    setClaiming(true)
    setNotice('')
    try {
      const { data } = await client.post('/me/rewards/daily')
      setNotice(`Daily reward claimed: ${money(data.granted)}.`)
      await Promise.all([fetchMe(), loadRewards(), loadTxns()])
    } catch (err) {
      setNotice(errMsg(err, 'Could not claim the daily reward.'))
    } finally {
      setClaiming(false)
    }
  }

  async function saveLimit() {
    setRgBusy('limit')
    setRgNotice('')
    try {
      const value = limitInput.trim() === '' ? null : parseFloat(limitInput)
      await client.put('/me/limits', { daily_deposit_limit: value })
      await fetchMe()
      setRgNotice(value == null ? 'Daily deposit limit removed.' : `Daily deposit limit set to ${money(value)}.`)
    } catch (err) {
      setRgNotice(errMsg(err, 'Could not update your limit.'))
    } finally {
      setRgBusy('')
    }
  }

  async function selfExclude(days) {
    if (!window.confirm(`Lock your account out of deposits and wagering for ${days} days? This cannot be undone.`)) {
      return
    }
    setRgBusy('exclude')
    setRgNotice('')
    try {
      await client.post('/me/self-exclude', { days })
      await fetchMe()
      setRgNotice(`You are self-excluded for ${days} days. You can still withdraw your balance.`)
    } catch (err) {
      setRgNotice(errMsg(err, 'Could not set self-exclusion.'))
    } finally {
      setRgBusy('')
    }
  }

  async function deposit() {
    setDepositErr('')
    setNotice('')
    const amount = parseFloat(depositAmt)
    if (!amount || amount <= 0) {
      setDepositErr('Enter a valid amount.')
      return
    }
    setDepositBusy(true)
    try {
      const { data } = await client.post('/wallet/deposit', { amount })
      if (data?.checkout_url) {
        window.location.href = data.checkout_url
        return
      }
      setNotice(
        parseFloat(data?.bonus_granted ?? 0) > 0
          ? `Deposit complete — plus a ${money(data.bonus_granted)} welcome bonus!`
          : 'Deposit complete.'
      )
      setDepositAmt('')
      await Promise.all([fetchMe(), loadTxns(), loadRewards()])
    } catch (err) {
      setDepositErr(errMsg(err, 'Deposit failed.'))
    } finally {
      setDepositBusy(false)
    }
  }

  async function withdraw() {
    setWithdrawErr('')
    setNotice('')
    const amount = parseFloat(withdrawAmt)
    if (!amount || amount <= 0) {
      setWithdrawErr('Enter a valid amount.')
      return
    }
    setWithdrawBusy(true)
    try {
      const { data } = await client.post('/wallet/withdraw', { amount })
      setNotice(
        data?.fee > 0
          ? `Withdrawal requested: ${money(data.amount)} after a ${money(data.fee)} fee.`
          : 'Withdrawal requested.'
      )
      setWithdrawAmt('')
      setQuote(null)
      await Promise.all([fetchMe(), loadTxns()])
    } catch (err) {
      setWithdrawErr(errMsg(err, 'Withdrawal failed.'))
    } finally {
      setWithdrawBusy(false)
    }
  }

  return (
    <div className="min-h-screen bg-graphite-950 text-steel-100">
      <header className="sticky top-0 z-40 border-b border-line-dark bg-graphite-950/90 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-5xl items-center justify-between px-4 sm:px-6">
          <Logo to="/tables" light />
          <button
            type="button"
            onClick={() => navigate('/tables')}
            className="rounded-md border border-line-dark px-4 py-2 text-xs font-semibold uppercase tracking-wide text-steel-100 transition-colors hover:border-accent hover:text-accent"
          >
            Tables
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 pb-20 pt-8 sm:px-6 sm:pt-10">
        {/* Balance */}
        <section className="text-center">
          <div className="text-[10px] font-medium uppercase tracking-[0.28em] text-steel-500">
            Balance
          </div>
          <div className="mt-2 font-display text-5xl font-black italic leading-none text-white sm:text-6xl">
            {user ? money(user.balance) : '-'}
          </div>
          {notice && <p className="mt-3 text-sm text-accent">{notice}</p>}
        </section>

        {/* Rollover gate. Only shown while something is still owed. */}
        {rollover > 0 && (
          <div className="mt-6 rounded-lg border border-accent/40 bg-accent/[0.07] p-4 text-sm">
            <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
              <span className="font-medium text-white">
                Wager {money(rollover)} more before you can withdraw
              </span>
              <span className="text-xs text-steel-500">1x play-through</span>
            </div>
            <p className="mt-1 text-xs leading-relaxed text-steel-400">
              Deposits unlock for withdrawal once played into a match. Burns
              down every time a match you&apos;re in settles.
            </p>
          </div>
        )}

        {/* Daily reward. Only shown when the reward feature is on. */}
        {rewards && parseFloat(rewards.daily_amount) > 0 && (
          <div className="mt-6 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line-dark bg-graphite-900 p-4">
            <div>
              <div className="text-sm font-medium text-white">
                Daily reward · {money(rewards.daily_amount)}
              </div>
              <p className="mt-0.5 text-xs text-steel-500">
                {rewards.daily_available
                  ? 'Claim a small bonus every day you play.'
                  : `Next reward ${formatDate(rewards.daily_next_at)}. Come back tomorrow.`}
              </p>
            </div>
            <button
              type="button"
              onClick={claimDaily}
              disabled={claiming || !rewards.daily_available}
              className="rounded-md bg-accent px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-accent-dark disabled:cursor-not-allowed disabled:opacity-40"
            >
              {claiming ? 'Claiming…' : rewards.daily_available ? 'Claim' : 'Claimed'}
            </button>
          </div>
        )}

        {/* Deposit / Withdraw. Stack on phones, side-by-side from sm+. */}
        <section className="mt-8 grid gap-4 sm:mt-10 sm:grid-cols-2 sm:gap-6">
          <div className="rounded-xl border border-line-dark bg-graphite-900 p-5">
            <h2 className="font-display text-lg font-bold uppercase italic tracking-tight text-white">
              Deposit
            </h2>
            <div className="mt-3 flex items-center rounded-md border border-line-dark bg-graphite-800 px-3">
              <span className="text-sm text-steel-500">$</span>
              <input
                type="number"
                inputMode="decimal"
                min="1"
                step="1"
                value={depositAmt}
                placeholder="0.00"
                onChange={(e) => setDepositAmt(e.target.value)}
                className="w-full bg-transparent px-2 py-2.5 text-sm text-white outline-none placeholder:text-steel-500"
              />
            </div>
            <button
              type="button"
              onClick={deposit}
              disabled={depositBusy}
              className="mt-3 w-full rounded-md bg-accent px-4 py-2.5 text-xs font-semibold uppercase tracking-wide text-white transition-colors hover:bg-accent-dark disabled:opacity-40"
            >
              {depositBusy ? 'Processing…' : 'Deposit'}
            </button>
            <div className="mt-2">
              <InlineError message={depositErr} />
            </div>
          </div>

          <div className="rounded-xl border border-line-dark bg-graphite-900 p-5">
            <h2 className="font-display text-lg font-bold uppercase italic tracking-tight text-white">
              Withdraw
            </h2>
            <div className="mt-3 flex items-center rounded-md border border-line-dark bg-graphite-800 px-3">
              <span className="text-sm text-steel-500">$</span>
              <input
                type="number"
                inputMode="decimal"
                min="1"
                step="1"
                value={withdrawAmt}
                placeholder="0.00"
                onChange={(e) => setWithdrawAmt(e.target.value)}
                className="w-full bg-transparent px-2 py-2.5 text-sm text-white outline-none placeholder:text-steel-500"
              />
            </div>
            {/* Fee breakdown. The fee touches profit only; own deposit back is
                always free. */}
            {quote && (
              <dl className="mt-3 space-y-1 rounded-md border border-line-dark bg-graphite-950 p-3 text-xs">
                <Row k="Your funds (no fee)" v={money(quote.own_funds)} />
                <Row k="Profit" v={money(quote.profit)} />
                <Row
                  k={`Fee (${parseFloat(quote.fee_percent)}% of profit)`}
                  v={`-${money(quote.fee)}`}
                  muted
                />
                <div className="mt-1 flex items-center justify-between border-t border-line-dark pt-1 text-sm font-semibold text-white">
                  <dt>You receive</dt>
                  <dd>{money(quote.you_receive)}</dd>
                </div>
              </dl>
            )}
            <button
              type="button"
              onClick={withdraw}
              disabled={withdrawBusy || (quote && !quote.can_withdraw)}
              className="mt-3 w-full rounded-md border border-line-dark px-4 py-2.5 text-xs font-semibold uppercase tracking-wide text-steel-100 transition-colors hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-40"
            >
              {withdrawBusy
                ? 'Processing…'
                : quote && !quote.can_withdraw
                  ? 'Locked'
                  : 'Withdraw'}
            </button>
            <div className="mt-2">
              <InlineError
                message={
                  withdrawErr ||
                  (quote && !quote.can_withdraw ? quote.reason : '')
                }
              />
            </div>
          </div>
        </section>

        {/* Transactions. Card list on phones (the four-column table would
            need a horizontal scroller); real table from sm+. */}
        <section className="mt-10 sm:mt-12">
          <h2 className="text-[10px] font-medium uppercase tracking-[0.28em] text-steel-500">
            Transactions
          </h2>

          {txnsLoaded && txns.length === 0 && (
            <p className="mt-6 text-sm text-steel-500">No transactions yet.</p>
          )}

          {txns.length > 0 && (
            <>
              <ul className="mt-3 divide-y divide-line-dark border-y border-line-dark sm:hidden">
                {txns.map((t) => (
                  <li key={t.id} className="flex items-center justify-between py-3">
                    <div className="min-w-0">
                      <div className="font-medium text-steel-100">{t.type}</div>
                      <div className="text-[11px] text-steel-500">
                        {formatDate(t.created_at)}
                      </div>
                    </div>
                    <div className="shrink-0 font-display text-sm font-bold text-white">
                      {money(t.amount)}
                    </div>
                  </li>
                ))}
              </ul>

              <table className="mt-4 hidden w-full text-sm sm:table">
                <thead>
                  <tr className="border-b border-line-dark text-left text-steel-500">
                    <th className="py-2 text-[10px] font-medium uppercase tracking-[0.2em]">
                      Date
                    </th>
                    <th className="py-2 text-[10px] font-medium uppercase tracking-[0.2em]">
                      Type
                    </th>
                    <th className="py-2 text-[10px] font-medium uppercase tracking-[0.2em]">
                      Amount
                    </th>
                    <th className="py-2 text-[10px] font-medium uppercase tracking-[0.2em]">
                      Balance after
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line-dark">
                  {txns.map((t) => (
                    <tr key={t.id} className="text-steel-100">
                      <td className="py-3 text-steel-500">
                        {formatDate(t.created_at)}
                      </td>
                      <td className="py-3">{t.type}</td>
                      <td className="py-3 font-medium">{money(t.amount)}</td>
                      <td className="py-3 text-steel-400">
                        {money(t.balance_after)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </section>

        {/* Responsible gaming. Self-set a deposit cap, or take a break. */}
        <section className="mt-12">
          <h2 className="text-[10px] font-medium uppercase tracking-[0.28em] text-steel-500">
            Responsible gaming
          </h2>
          <div className="mt-3 grid gap-4 sm:grid-cols-2">
            <div className="rounded-xl border border-line-dark bg-graphite-900 p-5">
              <div className="text-sm font-medium text-white">Daily deposit limit</div>
              <p className="mt-1 text-xs text-steel-500">
                {user?.daily_deposit_limit != null
                  ? `Currently ${money(user.daily_deposit_limit)} per 24h.`
                  : 'No limit set. Cap how much you can deposit in a day.'}
              </p>
              <div className="mt-3 flex items-center gap-2">
                <div className="flex flex-1 items-center rounded-md border border-line-dark bg-graphite-800 px-3">
                  <span className="text-sm text-steel-500">$</span>
                  <input
                    type="number"
                    min="0"
                    step="1"
                    value={limitInput}
                    placeholder="Amount (blank = none)"
                    onChange={(e) => setLimitInput(e.target.value)}
                    className="w-full bg-transparent px-2 py-2 text-sm text-white outline-none placeholder:text-steel-500"
                  />
                </div>
                <button
                  type="button"
                  onClick={saveLimit}
                  disabled={rgBusy === 'limit'}
                  className="rounded-md border border-line-dark px-4 py-2 text-sm font-medium text-steel-100 transition-colors hover:border-accent hover:text-accent disabled:opacity-40"
                >
                  Save
                </button>
              </div>
            </div>

            <div className="rounded-xl border border-line-dark bg-graphite-900 p-5">
              <div className="text-sm font-medium text-white">Take a break</div>
              <p className="mt-1 text-xs text-steel-500">
                {user?.self_excluded_until
                  ? `Self-excluded until ${formatDate(user.self_excluded_until)}. You can still withdraw.`
                  : 'Lock yourself out of deposits and wagering. Withdrawals stay open.'}
              </p>
              {!user?.self_excluded_until && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {[7, 30, 90].map((d) => (
                    <button
                      key={d}
                      type="button"
                      onClick={() => selfExclude(d)}
                      disabled={rgBusy === 'exclude'}
                      className="rounded-md border border-line-dark px-4 py-2 text-sm font-medium text-steel-100 transition-colors hover:border-loss hover:text-loss disabled:opacity-40"
                    >
                      {d} days
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
          {rgNotice && <p className="mt-3 text-sm text-accent">{rgNotice}</p>}
          <p className="mt-4 text-xs leading-relaxed text-steel-600">
            Must be 18+ (or the legal age where you live) to play. Wagering
            involves risk; only stake what you can afford to lose. If gambling
            stops being fun, take a break or seek help.
          </p>
        </section>
      </main>
    </div>
  )
}

function Row({ k, v, muted }) {
  return (
    <div className="flex items-center justify-between">
      <dt className="text-steel-500">{k}</dt>
      <dd className={muted ? 'text-steel-500' : 'text-steel-100'}>{v}</dd>
    </div>
  )
}
