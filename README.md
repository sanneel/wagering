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
| POST | `/webhook/faceit` | FACEIT match events → settle / refund |
| POST | `/webhook/payed` | Payed.co payment events → credit deposits |
| POST | `/wallet/deposit` | Initiate a Payed.co hosted checkout |
| POST | `/wallet/withdraw` | Debit balance + request Payed.co payout |
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
organizer API once that account exists. The compliance
posture here (geofencing, VPN blocking, KYC-gated withdrawals via `is_verified`)
is a technical baseline, not legal advice; real-money wagering is heavily
regulated and you should confirm licensing for every jurisdiction you serve.
```
