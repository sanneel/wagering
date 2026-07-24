"""Retention bonuses + responsible-gaming gates, over the real ASGI app.

    DATABASE_URL="sqlite+aiosqlite:///./br.db" REDIS_ENABLED=false DEMO_MODE=true \
        PYTHONPATH=. python3 tests/test_bonus_rg.py
"""
import asyncio
from decimal import Decimal

import httpx

import app.models  # noqa: F401 — register the ORM tables on Base.metadata
from app.database import Base, engine

PASS = FAIL = 0


def check(n, c):
    global PASS, FAIL
    if c: PASS += 1; print(f"  PASS  {n}")
    else: FAIL += 1; print(f"  FAIL  {n}")


async def main():
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.drop_all)
        await c.run_sync(Base.metadata.create_all)

    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as cl:
        tok = (await cl.post("/auth/demo")).json()["access_token"]
        H = {"Authorization": f"Bearer {tok}"}

        # ── Welcome bonus on first deposit (50% up to $10) ──
        r = (await cl.post("/wallet/deposit", json={"amount": 20}, headers=H)).json()
        check("first deposit grants $10 welcome bonus", Decimal(str(r["bonus_granted"])) == Decimal("10.00"))
        me = (await cl.get("/me", headers=H)).json()
        # 500 start + 20 deposit + 10 bonus = 530
        check("balance reflects deposit + welcome", Decimal(str(me["balance"])) == Decimal("530.00"))

        r2 = (await cl.post("/wallet/deposit", json={"amount": 20}, headers=H)).json()
        check("second deposit grants no welcome bonus", Decimal(str(r2["bonus_granted"])) == Decimal("0.00"))

        # ── Daily reward ──
        rw = (await cl.get("/me/rewards", headers=H)).json()
        check("daily reward available at first", rw["daily_available"] is True)
        d = (await cl.post("/me/rewards/daily", headers=H))
        check("claim daily -> 200", d.status_code == 200)
        check("daily grants $0.50", Decimal(str(d.json()["granted"])) == Decimal("0.50"))
        d2 = await cl.post("/me/rewards/daily", headers=H)
        check("second daily claim rejected", d2.status_code == 400)
        rw2 = (await cl.get("/me/rewards", headers=H)).json()
        check("daily now on cooldown", rw2["daily_available"] is False and rw2["daily_next_at"] is not None)

        # ── Deposit limit ──
        await cl.put("/me/limits", json={"daily_deposit_limit": 25}, headers=H)
        # already deposited 40 in the last 24h, so any further deposit exceeds $25
        over = await cl.post("/wallet/deposit", json={"amount": 10}, headers=H)
        check("deposit over the daily limit is rejected", over.status_code == 403)
        await cl.put("/me/limits", json={"daily_deposit_limit": None}, headers=H)
        ok = await cl.post("/wallet/deposit", json={"amount": 10}, headers=H)
        check("clearing the limit re-allows deposits", ok.status_code == 200)

        # ── Self-exclusion blocks wagering + deposits, not viewing ──
        await cl.post("/me/self-exclude", json={"days": 7}, headers=H)
        excl_dep = await cl.post("/wallet/deposit", json={"amount": 10}, headers=H)
        check("self-excluded deposit rejected", excl_dep.status_code == 403)
        excl_tab = await cl.post("/tables", json={"wager_amount": 5, "team_size": 1}, headers=H)
        check("self-excluded table create rejected", excl_tab.status_code == 403)
        excl_spin = await cl.post("/spincounter", json={"entry_fee": 3, "size": 4}, headers=H)
        check("self-excluded SpinCounter create rejected", excl_spin.status_code == 403)
        still_me = await cl.get("/me", headers=H)
        check("self-excluded user can still view /me", still_me.status_code == 200)

    print(f"\n=== {PASS} passed, {FAIL} failed ===")
    await engine.dispose()
    raise SystemExit(1 if FAIL else 0)


if __name__ == "__main__":
    asyncio.run(main())
