"""HTTP-level test of /webhook/faceit routing a SpinCounter game result.

Signs a finished-match payload and posts it to the real ASGI app, verifying the
webhook resolves the bracket game and advances/settles it.

    DATABASE_URL="sqlite+aiosqlite:///./w.db" REDIS_ENABLED=false DEMO_MODE=false \
      FACEIT_WEBHOOK_SECRET=whsec PYTHONPATH=. python3 scratchpad/webhook_test.py
"""
import asyncio
import hashlib
import hmac
import json
from decimal import Decimal

import httpx
from sqlalchemy import select

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.models import SpinStatus, Tournament, TournamentGame, User
from app.services import faceit, tournament_service as ts

PASS = FAIL = 0


def check(n, c):
    global PASS, FAIL
    if c: PASS += 1; print(f"  PASS  {n}")
    else: FAIL += 1; print(f"  FAIL  {n}")


async def fake_create(a, b, match_ref):
    return f"faceit-{match_ref}"


faceit.create_private_match = fake_create


def sign(body: bytes) -> str:
    return hmac.new(settings.faceit_webhook_secret.encode(), body, hashlib.sha256).hexdigest()


async def mkuser(name):
    async with SessionLocal() as db:
        u = User(faceit_id=f"fid-{name}", faceit_username=name, faceit_elo=1000,
                 balance=Decimal("100.00"), is_verified=True)
        db.add(u); await db.commit(); await db.refresh(u)
        return u.id, u.faceit_id


async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    from app.main import app

    a_id, a_fid = await mkuser("wa")
    b_id, b_fid = await mkuser("wb")
    async with SessionLocal() as db:
        t = await ts.open_tournament(db, creator_id=a_id, entry_fee=Decimal("5.00"), size=2)
        tid = t.id
    async with SessionLocal() as db:
        await ts.join_tournament(db, tournament_id=tid, user_id=b_id)

    async with SessionLocal() as db:
        game = (await db.execute(
            select(TournamentGame).where(TournamentGame.tournament_id == tid))).scalar_one()
    check("game has a faceit match id", game.faceit_match_id is not None)

    # Build a FACEIT finished payload where faction1 (player a) wins.
    payload = {
        "id": "evt-1",
        "event": "match_status_finished",
        "payload": {
            "id": game.faceit_match_id,
            "results": {"winner": "faction1"},
            "teams": {
                "faction1": {"roster": [{"id": a_fid}]},
                "faction2": {"roster": [{"id": b_fid}]},
            },
        },
    }
    body = json.dumps(payload).encode()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Bad signature rejected.
        r_bad = await client.post("/webhook/faceit", content=body,
                                  headers={"X-Faceit-Signature": "deadbeef"})
        check("bad signature -> 401", r_bad.status_code == 401)

        # Good signature settles the bracket.
        r = await client.post("/webhook/faceit", content=body,
                              headers={"X-Faceit-Signature": sign(body)})
        check("valid finished webhook -> 200", r.status_code == 200)
        check("webhook reports bracket_advanced", r.json().get("status") == "bracket_advanced")

        # Duplicate event id -> idempotent duplicate_ignored (Redis off => not deduped,
        # so it reprocesses; the service no-ops on the finished game instead).
        r2 = await client.post("/webhook/faceit", content=body,
                               headers={"X-Faceit-Signature": sign(body)})
        check("replayed webhook still 200 (no double-settle error)", r2.status_code == 200)

    async with SessionLocal() as db:
        tt = (await db.execute(select(Tournament).where(Tournament.id == tid))).scalar_one()
        champ = tt.champion_id
        winner_bal = (await db.execute(select(User.balance).where(User.id == a_id))).scalar_one()
    check("champion is faction1 player", champ == a_id)
    # a: 100 - 5 entry + 8.50 champion pool ($10 less the 15% jackpot rake) =
    # 103.50, plus the jackpot if a also caught it.
    check("winner balance >= 103.50 (champion pool paid)", winner_bal >= Decimal("103.50"))

    print(f"\n=== {PASS} passed, {FAIL} failed ===")
    await engine.dispose()
    raise SystemExit(1 if FAIL else 0)


if __name__ == "__main__":
    asyncio.run(main())
