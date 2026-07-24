#!/usr/bin/env bash
# Run the money-critical harnesses against a throwaway SQLite DB.
# No Postgres/Redis needed. From the repo root:  bash tests/run.sh
set -euo pipefail
cd "$(dirname "$0")/.."

export REDIS_ENABLED=false
export PYTHONPATH="$PWD"
# The harnesses re-enable the config-disabled 2-player bracket so its still-
# supported code path stays covered; the app default (4,8) is unaffected.
export SPIN_SIZES="2,4,8"

fail=0
run() {
  local name="$1" db="$2"; shift 2
  echo "── $name ──"
  # `env` so the VAR=val passthrough is parsed as assignments (a quoted "$@"
  # expansion is not treated as an assignment by the shell).
  if env DATABASE_URL="sqlite+aiosqlite:///./$db" "$@" python3 "tests/$name"; then :; else fail=1; fi
  rm -f "./$db" "./$db"-* 2>/dev/null || true
  echo
}

run test_scenarios.py           test_scen.db  DEMO_MODE=true
run test_faceit_integration.py  test_fac.db   DEMO_MODE=false
run test_webhook.py             test_wh.db    DEMO_MODE=false FACEIT_WEBHOOK_SECRET=whsec

exit $fail
