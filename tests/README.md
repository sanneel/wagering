# Tests

Money-critical harnesses that run against a throwaway SQLite database — no
Postgres or Redis required. From the repo root:

```bash
bash tests/run.sh
```

They assert the invariants that matter most for a wagering ledger:

- **test_scenarios.py** (51 checks) — table and SpinCounter lifecycles, money
  conservation, 2/4/8-player brackets, every error path, leave/cancel refunds,
  post-lock guards, report idempotency, and rollover burn.
- **test_faceit_integration.py** (15 checks) — a per-game FACEIT match is created
  on lock and on each advance, webhook-driven results settle the bracket,
  duplicate finished-webhooks are no-ops, and unknown matches resolve to `None`.
- **test_webhook.py** (7 checks) — the real `/webhook/faceit` HTTP path: bad
  signature → 401, finished → settle → 200, replay safety, champion paid.

Each script exits non-zero on any failed assertion, so `tests/run.sh` returns a
usable status for CI.

> These are plain assertion scripts rather than a `pytest` suite — the next step
> (see `docs/PLATFORM_REVIEW.md`, item L4) is to fold them into `pytest` and run
> them in CI alongside `ruff`, `mypy` and the frontend build.
