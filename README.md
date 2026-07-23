# 1v1wager API

FastAPI backend for a P2P CS2 skill-wagering platform (1v1wager.com).

Stack: **FastAPI · PostgreSQL (async SQLAlchemy 2.0 / asyncpg) · Redis · Payed.co · FACEIT**

## Layout

```
app/
  main.py               # app + middleware wiring, lifespan
  config.py             # env-driven settings
  database.py           # async engine / session / Base
  redis_client.py       # match-state + webhook idempotency helpers
  models.py             # User, Match, Transaction
  schemas.py            # Pydantic request/response models
  security.py           # JWT issue/verify, get_current_user
  middleware/
    geofencing.py       # ipinfo.io region block + IPQualityScore VPN block
  services/
    faceit.py           # OAuth exchange, userinfo, elo, create match
    payed.py            # deposit checkout + payout + webhook signature
    geo.py              # cached ipinfo + IPQS lookups
    ledger.py           # locked read-modify-write balance primitives
    match_service.py    # create/accept/settle/refund state machine
  routers/
    auth.py  users.py  match.py  wallet.py  webhook.py
```

## Endpoints

| Method | Path | Description |
| --- | --- | --- |
| GET  | `/auth/faceit` | Start FACEIT OAuth (or, in demo mode, mint a guest) |
| GET  | `/auth/faceit/callback` | OAuth return → redirects to `FRONTEND_URL/auth/callback?token=<jwt>` |
| POST | `/auth/faceit` | Programmatic code→JWT exchange (JSON) |
| POST | `/auth/demo` | Create a throwaway guest with a starting balance (demo mode) |
| GET  | `/me` | Current user profile + balance |
| GET  | `/me/matches` | Current user's match history (opponent, W/L, payout) |
| GET  | `/matches/recent` | Last 10 finished matches — **public, no auth** |
| GET  | `/formats` | Formats this server accepts (`1v1`, `2v2`, `5v5`) — **public, no auth** |
| GET  | `/tables` | Open tables still filling; `?team_size=` filters by format |
| POST | `/tables` | Open a table (`wager_amount`, `team_size`), escrow the creator's stake (→ PENDING) |
| POST | `/tables/{id}/join` | Take a seat (optional `team`); locks the table when the last seat fills |
| POST | `/tables/{id}/leave` | Give up a seat while still PENDING, refund that stake |
| DELETE | `/match/{id}/cancel` | Cancel a not-yet-finished table, refund every seat |
| GET  | `/match/{id}` | Table/match status with the full seat list |
| GET  | `/spincounter/config` | Bracket sizes, entry bounds, the wheel — drives the UI |
| GET  | `/spincounter` | Open brackets still filling; `?size=` filters by bracket size |
| POST | `/spincounter` | Open a bracket (`entry_fee`, `size`), escrow the creator's entry (→ PENDING) |
| POST | `/spincounter/{id}/join` | Take a seat; locks + spins the wheel when the last seat fills |
| POST | `/spincounter/{id}/leave` | Give up a seat while still PENDING, refund that entry |
| DELETE | `/spincounter/{id}/cancel` | Cancel a still-filling bracket, refund every entry |
| GET  | `/spincounter/{id}` | Bracket status: wheel result, entries, and every game |
| POST | `/webhook/faceit` | FACEIT match events → settle / refund |
| POST | `/webhook/payed` | Payed.co payment events → credit deposits |
| GET  | `/party` | The caller's party (members, Team Balance, activity log), or null |
| POST | `/party` | Create a party (caller becomes leader) |
| POST | `/party/join` | Join via `invite_code` |
| POST | `/party/leave` | Leave with your pool share; the leader leaving disbands |
| POST | `/party/kick/{user_id}` | Leader removes a member (their share goes with them) |
| POST | `/party/split-mode` | Leader sets PROPORTIONAL / LEADER (snapshotted per match) |
| POST | `/party/contribute` | Move personal balance into the Team Balance |
| POST | `/party/reclaim` | Take your own share back out |
| POST | `/party/distribute` | Leader pays a member from the pool (capped — see below) |
| POST | `/wallet/deposit` | Initiate a Payed.co hosted checkout |
| POST | `/wallet/withdraw` | Debit balance + request Payed.co payout (fee on profit only) |
| GET  | `/wallet/quote` | Preview a withdrawal: own funds vs profit, fee, rollover gate |
| GET  | `/wallet/transactions` | Paginated ledger history |

## Tables and formats

A **table** is two sides of `team_size` seats, and every seat is one escrowed
stake. `team_size` is just a number (1 → 1v1, 2 → 2v2, 5 → 5v5), and seats live
in `match_participants` rather than fixed player columns — so the same rows and
the same code run every format.

Which formats are accepted is **config, not schema**: `ALLOWED_TEAM_SIZES`
(default `1,2,5`). Adding 3v3 is that list plus a label in the frontend's
`FORMAT_COPY` — no migration, no new endpoints. `GET /formats` publishes the
list so the UI builds its pickers from the server rather than hardcoding them.

## SpinCounter: 1v1 bracket tournaments with a Wheel of Fortune

A **SpinCounter** is a single-elimination 1v1 bracket. Everyone pays the same
`entry_fee`, escrowed at join exactly like a table seat (a `tournament_entries`
row is only ever written in the same transaction as its ESCROW debit, so a seat
never exists without money behind it). Bracket `size` is a power of two — `2` is
a straight final, `4` is semifinals + final, `8` adds quarterfinals — and the
allowed set is **config, not schema** (`SPIN_SIZES`).

The moment the last seat fills, the bracket **locks in one transaction**:

1. the prize pool is fixed at `entry_fee × size` (100% RTP by default — the
   champion takes the whole pot, `SPIN_RAKE_PERCENT=0`, same ethos as tables);
2. the **Wheel of Fortune** spins once — a weighted-random segment
   (`SPIN_WHEEL_SEGMENTS`, `amount:weight` pairs) picks a jackpot, and a
   randomly-drawn entrant wins it. The jackpot is a **house-funded promotional
   bonus**, credited as a `BONUS` ledger entry — it does **not** come out of the
   pool, which is why it can dwarf the buy-in. It raises the winner's rollover
   (`SPIN_WHEEL_ROLLOVER`) so it can't be cashed straight out; the segment
   weights govern the house's expected promo cost;
3. seeds are drawn at random and the round-1 games are created.

Games are then played 1v1, **best-of `SPIN_ROUNDS_BEST_OF`** (default 3). Each
winner advances into the next round's slot — round `r` slot `s` feeds round
`r+1` slot `s//2`, as player A when `s` is even, player B when odd — until the
final resolves and the champion is paid the pool. Every entrant played, so every
entry burns its owner's rollover at settle (losers included), the same
settle-time rule matches use.

So a player has **two ways to win from one buy-in**: the wheel jackpot (luck)
and the bracket prize pool (skill). All money moves through `ledger` and every
mutation locks the tournament row first, the same concurrency discipline as
tables. In demo mode bots fill the bracket, the wheel spins, and every game
auto-plays through to a champion.

## Parties and the Team Balance

Every player can lead a **party** (up to the largest allowed format). A party
queues as a block: it fits only formats with `team_size >= party size` — a duo
sees 2v2/5v5, a full five sees only 5v5 — and its members are always seated
together on one side. Only the leader queues; a member can't be committed to a
stake by anyone but the person the party agreed to follow.

Funding is **pooled and deliberately uneven**: members move money from their
personal balance into the party's **Team Balance** (`/party/contribute`), and
the pool pays the whole side's buy-in when the party queues. A sponsor can
cover everyone. Each member holds an **entitlement** — their proportional claim
on the pool — and every pool movement is logged (the hover log in the UI).

Winnings follow the party's **split mode**, snapshotted onto each seat at
escrow so flipping the toggle after seeing the result changes nothing:

- **PROPORTIONAL** — each winner is paid straight to their personal balance by
  their funded share of the side's buy-in. Fund 20%, take 20%.
- **LEADER** — the side's winnings bank into the Team Balance, raising each
  member's entitlement by their proportional share. The leader then pays
  members out (`/party/distribute`) — but **capped**: up to a member's own
  entitlement moves freely (it's theirs), anything above it comes out of the
  leader's entitlement and **raises the recipient's rollover requirement** by
  the gifted amount. A sponsored free-rider can be paid generously, but that
  money cannot leave the platform without being wagered through — which is
  what stops "Leader Decides" being a laundering rail between accounts.

Refunds mirror funding: a cancelled table returns each seat's slice to the
pool (or the player, for solo seats), and leaving/disbanding a party returns
every member's entitlement to their personal balance — pool money can never
strand or move to anyone but its proportional owner.

## Economics: zero rake, withdrawal fee, 1× rollover

Matches are **100% RTP** — the winning side takes the whole pot (`RAKE_PERCENT=0`;
the rake columns and maths stay, so reintroducing one is config, not a migration).
The house is paid on withdrawal instead:

- **Fee on profit only** (`WITHDRAWAL_FEE_PERCENT`, default 20%). Each user carries
  a `principal` — deposits made, less the deposited part already withdrawn. A
  withdrawal's first slice is matched against `principal` and is **never charged**;
  only the excess is profit and is taxed. Getting your own money back is free, so a
  player who deposits 100, loses 50 and withdraws the rest pays nothing. `principal`
  is **not** reduced by losing a match — losing your deposit doesn't make the next
  withdrawal profit. `GET /wallet/quote` previews the split before the user commits.
- **1× rollover** (`ROLLOVER_MULTIPLIER`). A deposit raises `rollover_requirement`;
  withdrawals are blocked while it's above zero. It burns down **only when a match
  settles**, by each participant's stake (losers included — they wagered too).
  Crucially *not* at escrow: otherwise you could open a table, cancel it for a full
  refund, and clear the requirement having played nothing. This is why there's no
  "deposited vs won" split wallet — you simply can't withdraw un-played deposits.
- The fee is its own `FEE` ledger row beside the `WITHDRAWAL`, so the ledger still
  sums to the balance and the house cut is auditable.

## Money model

- **Balances live in Postgres** and are the source of truth. Redis only holds
  volatile match state and webhook idempotency markers.
- Every mutation goes through `services/ledger.py`, which locks the user row
  (`SELECT ... FOR UPDATE`), applies a signed delta, and writes a `Transaction`
  row with the resulting `balance_after` — no partial updates.
- A seat is only ever written **in the same transaction as its ESCROW debit**,
  so a table can never hold a seat whose stake wasn't taken.
- **Settlement** (in `services/match_service.py`) runs each operation inside one
  DB transaction: opening escrows the creator; each join escrows that player and
  locks the table once the last seat fills; finishing credits the winning side
  `pot − rake` split evenly and sets FINISHED; cancel refunds every seat that was
  actually taken (so a half-filled 5v5 returns exactly what it took) and sets
  CANCELLED. Pot is `wager × 2 × team_size`; rake defaults to 10%
  (`RAKE_PERCENT`). An uneven split gives the sub-cent remainder to the first
  seat, so credits always sum to exactly the payout.
- Joins are serialised by locking the table row, and a unique
  `(match_id, user_id)` stops the same player taking two seats — two players
  cannot both claim the last seat.
- Webhooks are idempotent (Redis `SET NX`) and signature-verified (HMAC-SHA256).

## Geofencing

`GeofencingMiddleware` runs on every non-exempt request: it resolves the client
IP via ipinfo.io and checks IPQualityScore for VPN/proxy. Blocked regions
(`BLOCKED_REGIONS`, ISO country or `US-WA`-style region codes) and VPNs
(`BLOCK_VPN`) return **451**. Behaviour on provider outage is controlled by
`GEO_FAIL_OPEN`. Private/loopback IPs and `GEO_EXEMPT_PATHS` bypass checks.

## Running

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows;  source .venv/bin/activate on *nix
pip install -r requirements.txt
cp .env.example .env          # then fill in real credentials

# Postgres + Redis must be reachable per your .env
uvicorn app.main:app --reload
```

In non-production, tables are auto-created on startup. For production, generate
Alembic migrations (the dependency is included) instead of `create_all`, and set
`ENVIRONMENT=production` (which also disables auto-create and tightens CORS).

Interactive docs at `/docs`.

## Demo mode (zero external dependencies)

With `DEMO_MODE=true` the whole product is clickable without FACEIT, Payed,
Postgres, or Redis:

- **`GET /auth/faceit`** and **`POST /auth/demo`** mint a guest with a starting
  balance (`DEMO_START_BALANCE`) — no real OAuth.
- **Deposits/withdrawals** settle instantly against the balance (no Payed call).
- **A few open bot tables are seeded at startup** across the formats, so the
  lobby has something to browse and join — there is only ever one human in demo
  mode, and bots fill their own table within seconds of it opening.
- **Opening or joining a table** brings in bots for every unfilled seat (a 5v5
  needs nine), then it auto-settles (PENDING → LOCKED → FINISHED) with the
  human's side favoured 55/45. FACEIT is never called.
- Setting `REDIS_ENABLED=false` skips Redis (match-state cache + webhook dedupe
  become no-ops), and a `sqlite+aiosqlite://` `DATABASE_URL` runs on SQLite
  (WAL-mode, portable BIGINT→INTEGER PKs). So a full demo needs **only Python**.

Minimal demo `.env`:

```env
DEMO_MODE=true
REDIS_ENABLED=false
DATABASE_URL=sqlite+aiosqlite:///./demo.db
FRONTEND_URL=http://localhost:5173
JWT_SECRET=demo-secret
BLOCKED_REGIONS=
BLOCK_VPN=false
```

Turn `DEMO_MODE`/`REDIS_ENABLED` off and point at Postgres+Redis for production.

## Notes / integration TODOs

The FACEIT match-creation payload (`services/faceit.py::create_private_match`)
and the Payed.co request/response field names (`services/payed.py`) are
encapsulated but depend on your specific organizer/merchant account — verify
them against the live API contracts before going to production. In particular
`create_private_match` now sends a roster per side (`teams.faction1/faction2`)
to cover 2v2 and 5v5; the exact team payload needs checking against the
organizer API once that account exists.

SpinCounter rides the same FACEIT rails: each bracket game becomes its own 1v1
FACEIT match. `tournament_service.ensure_faceit_matches` creates one for every
game the moment both players are known (round-1 games at lock, later rounds as
each advances), links it in Redis (`faceit:game:*`), and `/webhook/faceit`
resolves a finished event back to the game and advances the bracket
(`report_game_by_faceit`). It is best-effort and idempotent — a duplicate
finished webhook is a no-op, and a FACEIT creation failure leaves the game ready
but matchless so a later advance retries it. One caveat to wire before going
live: if the **round-1** creations all fail (no later advance to retry them),
the bracket has no way to start — add an operator/cron retry of
`ensure_faceit_matches` for LOCKED tournaments, the SpinCounter analogue of the
"operator can cancel→refund a stuck LOCKED table" path. None of this runs in
demo mode, where the simulation reports games directly.

The compliance
posture here (geofencing, VPN blocking, KYC-gated withdrawals via `is_verified`)
is a technical baseline, not legal advice; real-money wagering is heavily
regulated and you should confirm licensing for every jurisdiction you serve.
```
