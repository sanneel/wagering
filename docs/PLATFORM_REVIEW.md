# Platform review & roadmap

A full-project pass over 1v1wager: what's built and wired, what's fixed, what's
risky, and what the platform still needs before it could run real money at
scale. Written to be read top-to-bottom — the ordering _is_ the priority.

_Last updated: 2026-07 (after the SpinCounter feature landed)._

> **Shipped since this review was first written** (see git log): the deposit
> double-credit window is closed and the production start-up guard now also
> requires Redis; the SpinCounter jackpot was refactored from a ~$47-per-$12
> money pit into a self-funding, EV-neutral model; a welcome + daily **bonus**
> system and self-service **responsible-gaming** controls (deposit limit,
> self-exclusion) plus an 18+ age gate and a Terms/RG page were added; and the
> economics are written up in [`PLATFORM_ECONOMICS.md`](PLATFORM_ECONOMICS.md).
> The **High** risks below (durable money idempotency, withdrawal state machine,
> admin/ops surface, anti-collusion, real KYC/AML) remain the priority — they
> need Alembic and supervised changes to the money path.

---

## 1. What this is

A peer-to-peer CS2 skill-wagering platform. Players sign in with FACEIT, deposit
via Payed.co, and stake money on matches whose outcome comes from FACEIT.

- **Backend** — FastAPI (async), SQLAlchemy async (Postgres in prod, SQLite for
  the zero-dependency demo), Redis for volatile match state, webhook idempotency
  and rate limiting.
- **Money** — a single `ledger` module: escrow → win/refund/fee/bonus, a
  `principal` cost-basis (fee-free allowance) and a `rollover_requirement`
  (deposits must be wagered through once before withdrawal). 100% RTP matches;
  the house is paid a fee on withdrawal _profit_ only.
- **Products** — Tables (1v1/2v2/5v5), Parties (pooled Team Balance with
  proportional / leader-decides splits), and SpinCounter (1v1 bracket
  tournaments with a house-funded jackpot counter).
- **Frontend** — React + Vite + Tailwind, dark "graphite" theme.
- **Compliance baseline** — geofencing + VPN blocking + KYC-gated withdrawals
  (`is_verified`).
- **Deploy** — Vercel serverless for the API, a separate frontend deploy that
  points at it via `VITE_API_BASE`.

## 2. What's wired and working

- Auth end-to-end: FACEIT OAuth → one-time `?code=` → `/auth/exchange` → JWT.
  Demo login mints a guest.
- Tables: open → join (escrow per seat) → lock → FACEIT match → webhook settle /
  cancel-refund. Parties fund seats from the pool with asymmetric contribution.
- SpinCounter: open → join → lock (fix pool, spin the jackpot counter, seed the
  bracket) → per-game FACEIT matches → webhook-advance → champion settle. Live
  brackets are fog-of-war (you only see your own opponent) and 2-player is
  config-disabled.
- Wallet: deposit (Payed checkout → webhook credit), withdraw (debit → payout →
  refund-on-fail), live fee/rollover quote, ledger history.
- History: `/me/matches` and now `/me/spincounters`, both surfaced on the
  dashboard.
- Money hygiene is well-tested for conservation, idempotent settle, refunds and
  rollover (see the harnesses in §7).

## 3. Fixed in this pass

| # | Was | Now |
|---|-----|-----|
| F1 | No guard on demo-friendly defaults — a prod deploy with `JWT_SECRET=change-me` had forgeable tokens; `DEMO_MODE=true` bypassed the payment provider | `_assert_production_safe()` refuses to boot when `ENVIRONMENT=production` and any of `JWT_SECRET` default / `DEMO_MODE` on / `REDIS_ENABLED` off; warns on missing webhook secrets |
| F2 | Deposit webhook idempotency was keyed on `payment_ref:event:status` — two success-event names (or Redis disabled) could **double-credit** a balance | Success credits now dedupe on `payment_ref` alone; a payment credits at most once. (Durable guarantee still wants a settled column — see H1.) |
| F3 | SpinCounter results were invisible in the UI (dashboard listed table matches only) | `GET /me/spincounters` + serializer (placement, jackpot, net) + a dashboard section |
| F4 | Stale README auth rows said `?token=` | Corrected to the one-time `?code=` / `/auth/exchange` flow |

## 4. Open risks — ranked

### High

- **H1 — Durable deposit idempotency.** F2 closes the common double-credit hole,
  but the single-credit guarantee still rests on the Redis dedupe marker. A
  belt-and-braces fix is a durable settled-state on the deposit row (a
  `settled_at`/status column, or a unique constraint on a processed-event id)
  so a credit is impossible to apply twice even with no Redis. Needs Alembic
  (see M2).
- **H2 — Withdrawal has a crash/ambiguity window.** `withdraw()` debits +
  commits, then calls the payout provider, then refunds on failure. If the
  process dies between commit and refund — or the payout call times out but the
  money actually left — ledger and provider diverge. Real systems model a
  `WithdrawalRequest` state machine (`requested → sent → settled/failed`) with
  an idempotency key to the provider and a reconciliation job.
- **H3 — No admin / operations surface.** There is no way to inspect the ledger,
  view/cancel/refund a stuck match, adjust a balance, resolve a dispute, or ban
  a user. A money platform cannot operate without this. Pair it with an
  immutable audit log of every operator action.
- **H4 — Anti-collusion / match integrity.** P2P wagering invites match-fixing:
  two colluding accounts agreeing an outcome, smurf sandbagging, or a user
  playing both sides from two accounts to clear rollover and cash out (paying
  only the profit fee). Nothing detects same-owner opponents (shared
  device/IP/payment instrument), repeated suspicious pairings, or anomalous
  score patterns. Needs a risk engine + payout holds on flagged activity.
- **H5 — Real KYC/AML.** `is_verified` is FACEIT `email_verified` — not identity
  verification or sanctions screening. Real-money withdrawal in most
  jurisdictions legally requires proper KYC/AML and tax reporting.

### Medium

- **M1 — Stuck-state recovery.** A table that LOCKs but whose FACEIT match
  creation fails holds escrow indefinitely; a SpinCounter whose round-1 FACEIT
  creations all fail can't start (documented in the README). There's no cron /
  admin path to retry FACEIT creation or auto-cancel→refund after a timeout.
- **M2 — No migrations.** `auto_create_tables` is `create_all` only, which never
  alters an existing table. Any schema change (including H1) needs Alembic
  before it can ship to an existing database.
- **M3 — Rate limiting is only on `/auth/demo`.** Deposit, withdraw, table /
  tournament create+join and party ops are unthrottled. Add per-user + per-IP
  limits on money-moving and creation endpoints.
- **M4 — Demo mode can't run on Vercel serverless.** The demo bot simulation and
  table/bracket seeding use fire-and-forget `asyncio` tasks that are killed when
  the function freezes, so a serverless demo shows empty/stuck lobbies. A hosted
  demo needs a persistent worker, or an external cron that ticks an
  "advance one step" endpoint. Production (webhook-driven) is unaffected.
- **M5 — FACEIT payloads are unverified.** `faceit.create_private_match` and the
  webhook's `_extract_winner` are best-guess shapes; they must be validated
  against a real FACEIT organizer account, including draws / technical results,
  before real matches settle on them.
- **M6 — No real-time updates or notifications.** Everything polls every 3–4s.
  Players aren't told when their table fills, their FACEIT match is ready, or a
  withdrawal completed. WebSocket/SSE + email/push would improve both UX and
  load — SpinCounter especially ("your match is ready").

### Lower

- **L1 — Responsible-gambling features** (deposit/loss limits, self-exclusion,
  cool-off, reality checks) are absent and are legally required in regulated
  markets.
- **L2 — Design consistency.** Only SpinCounter got the visual cleanup; Tables /
  Wallet / Dashboard / Landing still use the heavier "condensed-black-italic +
  many caps labels" style. Worth a consistent pass if the calmer look is
  preferred.
- **L3 — Discovery / engagement.** No leaderboards, player profiles, head-to-head
  records, seasons, or a persistent payout destination on the account. The
  public feed and Landing don't surface SpinCounter.
- **L4 — No committed tests / CI.** The scenario, FACEIT and webhook harnesses
  used to validate this work live outside the repo. They should be committed as
  a pytest suite with GitHub Actions running ruff + mypy + pytest + the frontend
  build (see §7).

## 5. Compliance & legal (platform-defining, not code)

Real-money wagering is heavily regulated and licensed jurisdiction-by-
jurisdiction, with AML/KYC, tax reporting and consumer-protection obligations.
The geofencing here is a _technical_ baseline, not legal cover. None of this is
a code task — it gates whether the platform can operate at all in a given
market, and should be settled before launch.

## 6. Suggested sequencing

1. **Operability & integrity first** — H3 (admin + audit log), H1/H2 + M2
   (durable money idempotency and a withdrawal state machine on Alembic), M1
   (stuck-state recovery), M3 (rate limits). Without these, real money is unsafe
   to run.
2. **Integrity & trust** — H4 (anti-collusion/risk engine), H5 (real KYC/AML),
   M5 (validate FACEIT payloads end-to-end against a live organizer account).
3. **Experience & growth** — M6 (real-time + notifications), L2 (design
   consistency), L3 (profiles, leaderboards, saved payout), L1 (responsible-
   gambling controls — required before any regulated launch).
4. **Quality gate throughout** — L4 (commit the test suites + CI) so all of the
   above ships with regression cover.

## 7. Test harnesses used

Kept out of the repo for now (recommend committing under `tests/` — L4). They
run against SQLite and assert the money-critical invariants:

- **scenarios** (51 checks) — table + SpinCounter lifecycles, money
  conservation, 2/4/8-player brackets, every error path, leave/cancel refunds,
  post-lock guards, report idempotency, rollover burn.
- **faceit** (15 checks) — per-game FACEIT match creation on lock/advance,
  webhook-driven bracket settle, duplicate-webhook idempotency, unknown-match
  handling.
- **webhook** (7 checks) — the real `/webhook/faceit` HTTP path: bad signature →
  401, finished → settle → 200, replay safety, champion paid.

All green at the time of writing (73 assertions).
