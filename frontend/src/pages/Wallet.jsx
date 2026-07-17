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

  useEffect(() => {
    loadTxns()
  }, [])

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
      setNotice('Deposit initiated.')
      setDepositAmt('')
      await Promise.all([fetchMe(), loadTxns()])
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
