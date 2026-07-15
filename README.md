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
| POST | `/match/create` | Create an **open** match (just `wager_amount`), escrow creator's stake (→ PENDING) |
| POST | `/match/{id}/accept` | Any opponent escrows stake, match LOCKED, FACEIT match created |
| DELETE | `/match/{id}/cancel` | Cancel a not-yet-finished match, refund escrow |
| GET  | `/match/{id}` | Match status (with nested `player1`/`player2` objects) |
| POST | `/webhook/faceit` | FACEIT match events → settle / refund |
| POST | `/webhook/payed` | Payed.co payment events → credit deposits |
| POST | `/wallet/deposit` | Initiate a Payed.co hosted checkout |
| POST | `/wallet/withdraw` | Debit balance + request Payed.co payout |
| GET  | `/wallet/transactions` | Paginated ledger history |

## Money model

- **Balances live in Postgres** and are the source of truth. Redis only holds
  volatile match state and webhook idempotency markers.
- Every mutation goes through `services/ledger.py`, which locks the user row
  (`SELECT ... FOR UPDATE`), applies a signed delta, and writes a `Transaction`
  row with the resulting `balance_after` — no partial updates.
- **Match settlement** (in `services/match_service.py`) runs each operation
  inside one DB transaction: create escrows P1; accept escrows P2 and sets
  LOCKED; finish credits the winner `pot − rake` and sets FINISHED; cancel/abort
  refunds both and sets CANCELLED. Rake defaults to 10% (`RAKE_PERCENT`).
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
- **Match creation** spawns a bot opponent (`1v1wager Bot`) that accepts, the
  match auto-settles ~9s later (PENDING → LOCKED → FINISHED) with a random
  winner. FACEIT is never called.
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
them against the live API contracts before going to production. The compliance
posture here (geofencing, VPN blocking, KYC-gated withdrawals via `is_verified`)
is a technical baseline, not legal advice; real-money wagering is heavily
regulated and you should confirm licensing for every jurisdiction you serve.
```
