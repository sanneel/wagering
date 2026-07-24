import { useNavigate } from 'react-router-dom'
import Logo from '../components/Logo'

// A plain, readable legal/RG page. This is baseline consumer-facing copy, not
// legal advice — real terms, licensing and jurisdiction rules must be reviewed
// by counsel before operating for real money (see docs/PLATFORM_REVIEW.md §5).
export default function Legal() {
  const navigate = useNavigate()
  return (
    <div className="min-h-screen bg-graphite-950 text-steel-100">
      <header className="border-b border-line-dark">
        <div className="mx-auto flex h-16 max-w-3xl items-center justify-between px-6">
          <Logo to="/" light />
          <button
            type="button"
            onClick={() => navigate(-1)}
            className="text-xs uppercase tracking-[0.2em] text-steel-500 transition-colors hover:text-steel-100"
          >
            Back
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-6 py-12">
        <h1 className="font-display text-4xl font-semibold tracking-tight text-white">
          Terms & responsible gaming
        </h1>
        <p className="mt-3 text-sm text-steel-500">
          Please read before playing. This is a summary of how the platform works
          and the protections available to you.
        </p>

        <Section title="Eligibility">
          You must be at least 18 years old (or the legal age of majority where
          you live) and physically located in a permitted region. Access from
          restricted regions and via VPN/proxy is blocked. We may require
          identity verification (KYC) before processing withdrawals.
        </Section>

        <Section title="How wagering works">
          You stake money on the outcome of your own competitive matches. Match
          results are determined by FACEIT, not by us — we settle strictly on the
          reported result. Your stake is held in escrow the moment a table locks
          and paid to the winning side when the match settles. Cancelled matches
          are refunded in full.
        </Section>

        <Section title="Deposits, withdrawals & fees">
          Getting your own deposited money back is always free. A fee applies only
          to profit (winnings above what you deposited). Deposits must be wagered
          through once before they can be withdrawn — this is shown clearly in
          your wallet. Payments are processed by our payment provider; funds are
          only credited once the provider confirms them.
        </Section>

        <Section title="Fair play">
          Match-fixing, collusion, multi-accounting, and using more than one
          account to play both sides are prohibited and will result in forfeited
          balances and a ban. Bonuses are for genuine play and carry wagering
          requirements; abuse voids them.
        </Section>

        <Section title="Responsible gaming">
          Wagering should be entertainment, never a way to make money or recover
          losses. You can protect yourself at any time from your wallet:
          <ul className="mt-3 list-disc space-y-1 pl-5">
            <li>Set a daily deposit limit.</li>
            <li>Self-exclude for 7, 30, or 90 days — this blocks deposits and
              wagering while still letting you withdraw your balance.</li>
          </ul>
          <p className="mt-3">
            If gambling stops being fun, take a break. For free, confidential
            support, contact a service such as{' '}
            <a
              href="https://www.begambleaware.org/"
              className="text-accent hover:underline"
              target="_blank"
              rel="noopener noreferrer"
            >
              BeGambleAware
            </a>{' '}
            or the National Problem Gambling Helpline (1-800-522-4700 in the US).
          </p>
        </Section>

        <p className="mt-10 text-xs leading-relaxed text-steel-600">
          This page is a plain-language summary, not a contract or legal advice.
          Real-money wagering is regulated and licensed differently in every
          jurisdiction; availability and terms may vary or be unavailable where
          you live.
        </p>
      </main>
    </div>
  )
}

function Section({ title, children }) {
  return (
    <section className="mt-8 border-t border-line-dark pt-6">
      <h2 className="font-display text-xl font-semibold text-white">{title}</h2>
      <div className="mt-2 text-sm leading-relaxed text-steel-400">{children}</div>
    </section>
  )
}
