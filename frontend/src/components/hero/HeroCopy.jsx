import InlineError from '../InlineError'

export default function HeroCopy({ onFaceit, onDemo, demoBusy, demoErr }) {
  return (
    <div className="js-copy relative z-10 max-w-xl">
      <p className="text-xs font-medium uppercase tracking-[0.28em] text-steel-500">
        Real-money CS2 duels
      </p>
      <h1 className="mt-4 font-display text-6xl font-semibold uppercase leading-[0.92] tracking-tight text-steel-100 sm:text-7xl lg:text-8xl">
        Put <span className="text-accent">real money</span>
        <br />
        on your aim.
      </h1>
      <p className="mt-6 max-w-md text-base leading-relaxed text-steel-400">
        1v1 servers, FACEIT verified. Lock a stake, win the round, take the
        pot. Payouts land in seconds.
      </p>
      <div className="mt-9 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={onFaceit}
          className="rounded-md bg-accent px-6 py-3 text-sm font-semibold text-white transition-colors hover:bg-accent-dark"
        >
          Connect with FACEIT
        </button>
        <button
          type="button"
          onClick={onDemo}
          disabled={demoBusy}
          className="rounded-md border border-line-dark px-6 py-3 text-sm font-semibold text-steel-100 transition-colors hover:border-steel-500 disabled:opacity-60"
        >
          {demoBusy ? 'Loading demo…' : 'Try the demo'}
        </button>
      </div>
      <div className="mt-3">
        <InlineError message={demoErr} />
      </div>
      <p className="mt-8 text-xs text-steel-500">
        18+ · Skill-based wagering · Not available in all regions
      </p>
    </div>
  )
}
