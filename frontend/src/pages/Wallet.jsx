import { useEffect, useState } from 'react'
import client from '../api/client'
import TopNav from '../components/TopNav'
import InlineError from '../components/InlineError'
import { useAuth } from '../context/AuthContext'
import { money, formatDate } from '../lib/format'

export default function Wallet() {
  const { user, fetchMe } = useAuth()

  const [depositAmt, setDepositAmt] = useState('')
  const [withdrawAmt, setWithdrawAmt] = useState('')
  const [depositErr, setDepositErr] = useState('')
  const [withdrawErr, setWithdrawErr] = useState('')
  const [depositBusy, setDepositBusy] = useState(false)
  const [withdrawBusy, setWithdrawBusy] = useState(false)
  const [notice, setNotice] = useState('')

  const [txns, setTxns] = useState([])
  const [txnsLoaded, setTxnsLoaded] = useState(false)

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
      // Backend returns a hosted checkout URL — send the user there to pay.
      if (data?.checkout_url) {
        window.location.href = data.checkout_url
        return
      }
      setNotice('Deposit initiated.')
      setDepositAmt('')
      await Promise.all([fetchMe(), loadTxns()])
    } catch (err) {
      setDepositErr(
        err?.response?.data?.detail
          ? String(err.response.data.detail)
          : 'Deposit failed.'
      )
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
      await client.post('/wallet/withdraw', { amount })
      setNotice('Withdrawal requested.')
      setWithdrawAmt('')
      await Promise.all([fetchMe(), loadTxns()])
    } catch (err) {
      setWithdrawErr(
        err?.response?.data?.detail
          ? String(err.response.data.detail)
          : 'Withdrawal failed.'
      )
    } finally {
      setWithdrawBusy(false)
    }
  }

  return (
    <div className="min-h-screen">
      <TopNav />

      <main className="mx-auto max-w-3xl px-4 py-10">
        {/* Balance */}
        <section className="text-center">
          <div className="text-xs uppercase tracking-wide text-muted">
            Balance
          </div>
          <div className="mt-2 text-5xl font-semibold text-ink">
            {user ? money(user.balance) : '—'}
          </div>
          {notice && <p className="mt-3 text-sm text-win">{notice}</p>}
        </section>

        {/* Deposit / Withdraw */}
        <section className="mt-10 grid gap-6 sm:grid-cols-2">
          <div className="rounded-lg border border-line p-5">
            <h2 className="font-medium text-ink">Deposit</h2>
            <div className="mt-3 flex items-center rounded-md border border-line px-3">
              <span className="text-sm text-muted">$</span>
              <input
                type="number"
                min="1"
                step="1"
                value={depositAmt}
                placeholder="0.00"
                onChange={(e) => setDepositAmt(e.target.value)}
                className="w-full bg-transparent px-2 py-2 text-sm text-ink outline-none placeholder:text-muted"
              />
            </div>
            <button
              type="button"
              onClick={deposit}
              disabled={depositBusy}
              className="mt-3 w-full rounded-md bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-dark disabled:opacity-60"
            >
              {depositBusy ? 'Processing…' : 'Deposit'}
            </button>
            <div className="mt-2">
              <InlineError message={depositErr} />
            </div>
          </div>

          <div className="rounded-lg border border-line p-5">
            <h2 className="font-medium text-ink">Withdraw</h2>
            <div className="mt-3 flex items-center rounded-md border border-line px-3">
              <span className="text-sm text-muted">$</span>
              <input
                type="number"
                min="1"
                step="1"
                value={withdrawAmt}
                placeholder="0.00"
                onChange={(e) => setWithdrawAmt(e.target.value)}
                className="w-full bg-transparent px-2 py-2 text-sm text-ink outline-none placeholder:text-muted"
              />
            </div>
            <button
              type="button"
              onClick={withdraw}
              disabled={withdrawBusy}
              className="mt-3 w-full rounded-md border border-ink px-4 py-2 text-sm font-medium text-ink hover:bg-ink hover:text-white disabled:opacity-60"
            >
              {withdrawBusy ? 'Processing…' : 'Withdraw'}
            </button>
            <div className="mt-2">
              <InlineError message={withdrawErr} />
            </div>
          </div>
        </section>

        {/* Transactions */}
        <section className="mt-12">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">
            Transactions
          </h2>
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[480px] text-sm">
              <thead>
                <tr className="border-b border-line text-left text-muted">
                  <th className="py-2 font-medium">Date</th>
                  <th className="py-2 font-medium">Type</th>
                  <th className="py-2 font-medium">Amount</th>
                  <th className="py-2 font-medium">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {txnsLoaded && txns.length === 0 && (
                  <tr>
                    <td colSpan={4} className="py-6 text-muted">
                      No transactions yet.
                    </td>
                  </tr>
                )}
                {txns.map((t) => (
                  <tr key={t.id} className="text-ink">
                    <td className="py-3 text-muted">
                      {formatDate(t.created_at)}
                    </td>
                    <td className="py-3">{t.type}</td>
                    <td className="py-3">{money(t.amount)}</td>
                    <td className="py-3 text-muted">
                      {t.status || 'completed'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </div>
  )
}
