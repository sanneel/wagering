import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import client, { API_BASE } from '../api/client'
import { useAuth } from '../context/AuthContext'
import { useInView } from '../hooks/useInView'
import HeroSection from '../components/hero/HeroSection'
import Logo from '../components/Logo'
import { money, formatDate } from '../lib/format'

const STEPS = [
  {
    n: '01',
    title: 'Connect FACEIT',
    body: 'Sign in with your FACEIT account. No passwords stored.',
  },
  {
    n: '02',
    title: 'Take a seat',
    body: '1v1, 2v2 or 5v5. Every seat is escrowed before the server starts.',
  },
  {
    n: '03',
    title: 'Winners get paid',
    body: 'Play it out. The pot, minus a 10% rake, splits in seconds.',
  },
]

export default function Landing() {
  const navigate = useNavigate()
  const { fetchMe } = useAuth()

  // The CTA promises tables, so send signed-in players straight there and let
  // everyone else sign in first — /auth/callback lands on /tables too.
  function connectFaceit() {
    if (localStorage.getItem('token')) {
      navigate('/tables')
      return
    }
    window.location.href = `${API_BASE}/auth/faceit`
  }
  const [matches, setMatches] = useState([])
  const [loaded, setLoaded] = useState(false)
  const [demoBusy, setDemoBusy] = useState(false)
  const [demoErr, setDemoErr] = useState('')

  const [stepsRef, stepsSeen] = useInView({ threshold: 0.15 })
  const [feedRef, feedSeen] = useInView({ threshold: 0.1 })

  async function tryDemo() {
    setDemoErr('')
    setDemoBusy(true)
    try {
      const { data } = await client.post('/auth/demo')
      localStorage.setItem('token', data.access_token)
      await fetchMe()
      navigate('/tables')
    } catch {
      setDemoErr('Demo is unavailable right now.')
      setDemoBusy(false)
    }
  }

  useEffect(() => {
    let active = true
    client
      .get('/matches/recent')
      .then(({ data }) => {
        if (active) setMatches(Array.isArray(data) ? data : [])
      })
      .catch(() => {
        if (active) setMatches([])
      })
      .finally(() => {
        if (active) setLoaded(true)
      })
    return () => {
      active = false
    }
  }, [])

  return (
    <div className="min-h-screen bg-graphite-950 text-steel-100">
      {/* Fixed nav — lives OUTSIDE the pinned hero so it survives the whole
          3D scroll sequence and every section after it. */}
      <header className="fixed inset-x-0 top-0 z-50">
        <div className="bg-gradient-to-b from-graphite-950/95 via-graphite-950/60 to-transparent pb-3 backdrop-blur-[2px]">
          <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
            <Logo to="/" light />
            <div className="flex items-center gap-4">
              <span className="hidden text-xs uppercase tracking-[0.24em] text-steel-500 lg:block">
                Skill is the house edge
              </span>
              <button
                type="button"
                onClick={connectFaceit}
                className="rounded-md bg-accent px-4 py-2 text-xs font-semibold uppercase tracking-wide text-white transition-colors hover:bg-accent-dark"
              >
                Connect FACEIT
              </button>
            </div>
          </div>
        </div>
      </header>

      <HeroSection
        onFaceit={connectFaceit}
        onDemo={tryDemo}
        demoBusy={demoBusy}
        demoErr={demoErr}
      />

      <main className="mx-auto max-w-6xl px-6">
        {/* How a wager runs — on desktop these three steps play as cards
            inside the hero scroll sequence, so the static grid is
            mobile-only. The CTA stays on all breakpoints below. */}
        <section
          ref={stepsRef}
          className={`border-t border-line-dark py-20 lg:hidden ${stepsSeen ? '' : 'opacity-0'}`}
        >
          <h2 className="text-xs font-medium uppercase tracking-[0.28em] text-steel-500">
            How a wager runs
          </h2>
          <div className="mt-10 grid gap-px overflow-hidden rounded-lg border border-line-dark bg-line-dark sm:grid-cols-3">
            {STEPS.map((s, idx) => (
              <div
                key={s.n}
                className={`bg-graphite-800 p-8 ${stepsSeen ? ['slide-up-delayed-1', 'slide-up-delayed-2', 'slide-up-delayed-3'][idx] : 'opacity-0'}`}
              >
                <div className="font-display text-3xl font-semibold text-accent">
                  {s.n}
                </div>
                <h3 className="mt-4 font-medium text-steel-100">{s.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-steel-400">
                  {s.body}
                </p>
              </div>
            ))}
          </div>
          {/* CTA after steps — conversion moment once the user understands the flow */}
          <div className={`mt-10 flex justify-center ${stepsSeen ? 'slide-up-delayed-3' : 'opacity-0'}`}>
            <button
              type="button"
              onClick={connectFaceit}
              className="rounded-md bg-accent px-8 py-3 text-sm font-semibold text-white transition-colors hover:bg-accent-dark"
            >
              Connect with FACEIT — it&apos;s free
            </button>
          </div>
        </section>

        {/* Desktop CTA — the step cards played inside the hero scroll, so
            this is the landing spot right after the pin releases. */}
        <section className="hidden border-t border-line-dark py-16 lg:flex lg:justify-center">
          <button
            type="button"
            onClick={connectFaceit}
            className="rounded-md bg-accent px-8 py-3 text-sm font-semibold text-white transition-colors hover:bg-accent-dark"
          >
            Connect with FACEIT — it&apos;s free
          </button>
        </section>

        {/* Recent matches */}
        <section
          ref={feedRef}
          className={`border-t border-line-dark py-20 ${feedSeen ? 'animate-fade-in' : 'opacity-0'}`}
        >
          <h2 className="text-xs font-medium uppercase tracking-[0.28em] text-steel-500">
            Recent matches
          </h2>

          <div className="mt-6 divide-y divide-line-dark border-y border-line-dark">
            {!loaded && <SkeletonRows />}
            {loaded && matches.length === 0 && <SkeletonRows blurred />}
            {loaded && matches.map((m) => (
              <RecentRow key={m.id} match={m} />
            ))}
          </div>
        </section>
      </main>

      <footer className="border-t border-line-dark">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-2 px-6 py-8 text-xs text-steel-500">
          <span>
            1v1wager — wager responsibly. Must be of legal age in your
            jurisdiction.
          </span>
          <span className="uppercase tracking-[0.24em]">EST. 2026</span>
        </div>
      </footer>
    </div>
  )
}

const FAKE_ROWS = [
  { fmt: '1v1', p1: 'xX_headshoT_Xx', p2: 'clutch_king99', wager: '$25.00', winner: 'xX_headshoT_Xx' },
  { fmt: '5v5', p1: 'Team A', p2: 'Team B', wager: '$10.00', winner: 'Team B' },
  { fmt: '2v2', p1: 'entry_frag +1', p2: 'NiKo_wannabe +1', wager: '$50.00', winner: 'entry_frag +1' },
  { fmt: '1v1', p1: 'one_tap_god', p2: 'spray_n_pray', wager: '$5.00', winner: null },
]

function SkeletonRows({ blurred = false }) {
  return (
    <div className={blurred ? 'relative select-none' : undefined}>
      {FAKE_ROWS.map((r, i) => (
        <div key={i} className="flex items-center justify-between py-4 text-sm">
          <div className="flex items-center gap-2">
            <span className="w-8 font-display text-xs font-bold text-steel-500">{r.fmt}</span>
            <span className={r.winner === r.p1 ? 'font-medium text-steel-100' : 'text-steel-400'}>{r.p1}</span>
            <span className="text-steel-500">vs</span>
            <span className={r.winner === r.p2 ? 'font-medium text-steel-100' : 'text-steel-400'}>{r.p2}</span>
          </div>
          <div className="flex items-center gap-6">
            <span className="font-medium text-accent">{r.wager}</span>
            <span className="w-28 text-right text-steel-500">
              {r.winner ? `${r.winner} won` : 'in progress'}
            </span>
          </div>
        </div>
      ))}
      {blurred && (
        <div
          className="pointer-events-none absolute inset-0"
          style={{
            backdropFilter: 'blur(3px)',
            background: 'linear-gradient(to bottom, rgba(11,12,14,0) 0%, rgba(11,12,14,0.7) 60%, rgba(11,12,14,0.95) 100%)',
          }}
        />
      )}
      {blurred && (
        <p className="pb-2 pt-1 text-center text-xs text-steel-500">
          No matches yet — yours could be the first on this board.
        </p>
      )}
    </div>
  )
}

// A side reads as a name in 1v1, and as "name +N" once there's a team behind it.
function sideName(players, fallback) {
  if (!players?.length) return fallback
  const [first, ...rest] = players
  const name = first.faceit_username || fallback
  return rest.length ? `${name} +${rest.length}` : name
}

function RecentRow({ match }) {
  const size = match.team_size ?? 1
  const a = sideName(match.team_a, 'Team A')
  const b = sideName(match.team_b, 'Team B')
  const aWon = match.winning_team === 'A'
  const bWon = match.winning_team === 'B'

  return (
    <div className="flex items-center justify-between py-4 text-sm">
      <div className="flex items-center gap-2">
        <span className="w-8 font-display text-xs font-bold text-steel-500">
          {size}v{size}
        </span>
        <span className={aWon ? 'font-medium text-steel-100' : 'text-steel-400'}>
          {a}
        </span>
        <span className="text-steel-500">vs</span>
        <span className={bWon ? 'font-medium text-steel-100' : 'text-steel-400'}>
          {b}
        </span>
      </div>
      <div className="flex items-center gap-6">
        <span className="font-medium text-accent">{money(match.wager_amount)}</span>
        <span className="w-28 text-right text-steel-500">
          {match.winner_username
            ? `${match.winner_username} won`
            : formatDate(match.created_at)}
        </span>
      </div>
    </div>
  )
}
