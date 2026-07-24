"""FACEIT integration test for SpinCounter.

Monkeypatches the FACEIT client so no network is touched, runs with DEMO_MODE
false (so ensure_faceit_matches actually fires) and Redis disabled (so the
webhook path resolves games via the Postgres fallback). Verifies match creation
on lock, webhook-driven bracket advance, champion settlement, and idempotency.

    DATABASE_URL="sqlite+aiosqlite:///./f.db" REDIS_ENABLED=false \
        DEMO_MODE=false PYTHONPATH=. python3 scratchpad/faceit_test.py
"""
import asyncio
from decimal import Decimal

from sqlalchemy import select

from app.database import Base, SessionLocal, engine
from app.models import SpinStatus, Tournament, TournamentGame, User
from app.services import faceit, ledger, tournament_service as ts

PASS, FAIL = 0, 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  PASS  {name}")
    else:
        FAIL += 1; print(f"  FAIL  {name}")


# ── Fake FACEIT: deterministic match ids, records rosters seen ──
created = []


async def fake_create_private_match(team_a, team_b, match_ref):
    created.append({"ref": match_ref, "a": list(team_a), "b": list(team_b)})
    return f"faceit-{match_ref}"


faceit.create_private_match = fake_create_private_match


async def mkuser(name, bal="100.00"):
    async with SessionLocal() as db:
        u = User(faceit_id=f"fid-{name}", faceit_username=name, faceit_elo=1000,
                 balance=Decimal(bal), is_verified=True)
        db.add(u); await db.commit(); await db.refresh(u)
        return u.id, u.faceit_id


async def games_of(tid):
    async with SessionLocal() as db:
        return (await db.execute(
            select(TournamentGame).where(TournamentGame.tournament_id == tid)
            .order_by(TournamentGame.round, TournamentGame.slot))).scalars().all()


async def tget(tid):
    async with SessionLocal() as db:
        return (await db.execute(select(Tournament).where(Tournament.id == tid))).scalar_one()


async def bal(uid):
    async with SessionLocal() as db:
        return (await db.execute(select(User.balance).where(User.id == uid))).scalar_one()


async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    print("\n[FACEIT] 4-player bracket, webhook-driven, Redis off (Postgres lookup)")
    users = [await mkuser(f"f{i}") for i in range(4)]
    ids = [u for u, _ in users]
    fids = {u: f for u, f in users}

    async with SessionLocal() as db:
        t = await ts.open_tournament(db, creator_id=ids[0], entry_fee=Decimal("3.00"), size=4)
        tid = t.id
    for uid in ids[1:]:
        async with SessionLocal() as db:
            await ts.join_tournament(db, tournament_id=tid, user_id=uid)

    games = await games_of(tid)
    r1 = [g for g in games if g.round == 1]
    final = [g for g in games if g.round == 2][0]
    check("round-1 games got a FACEIT match id on lock", all(g.faceit_match_id for g in r1))
    check("final has no FACEIT match yet (players unknown)", final.faceit_match_id is None)
    check("two FACEIT matches created at lock", len(created) == 2)
    check("each created match is 1v1", all(len(c["a"]) == 1 and len(c["b"]) == 1 for c in created))

    # Report semifinals via the faceit-keyed path (as the webhook would).
    for g in r1:
        winner_uid = g.player_a_id
        async with SessionLocal() as db:
            res = await ts.report_game_by_faceit(
                db, faceit_match_id=g.faceit_match_id,
                winner_faceit_id=fids[winner_uid])
        check(f"semi {g.slot} reported via faceit id", res is not None)

    games = await games_of(tid)
    final = [g for g in games if g.round == 2][0]
    check("final now has both players", final.player_a_id and final.player_b_id)
    check("final got a FACEIT match after advance", final.faceit_match_id is not None)
    check("third FACEIT match created for the final", len(created) == 3)

    # Report the final.
    champ_uid = final.player_a_id
    async with SessionLocal() as db:
        await ts.report_game_by_faceit(
            db, faceit_match_id=final.faceit_match_id, winner_faceit_id=fids[champ_uid])
    t = await tget(tid)
    check("tournament FINISHED after final webhook", t.status == SpinStatus.FINISHED)
    check("champion is the reported winner", t.champion_id == champ_uid)

    # Idempotency: a duplicate finished webhook for the final is a quiet no-op.
    champ_bal = await bal(champ_uid)
    async with SessionLocal() as db:
        dup = await ts.report_game_by_faceit(
            db, faceit_match_id=final.faceit_match_id, winner_faceit_id=fids[champ_uid])
    check("duplicate final webhook returns the tournament (no error)", dup is not None)
    check("duplicate final webhook does not double-pay", await bal(champ_uid) == champ_bal)

    # Unknown faceit match id → None (not one of ours).
    async with SessionLocal() as db:
        none_res = await ts.report_game_by_faceit(
            db, faceit_match_id="faceit-does-not-exist", winner_faceit_id="whoever")
    check("unknown faceit match id resolves to None", none_res is None)

    # Wrong winner id on a real game → error.
    async with SessionLocal() as db:
        t2 = await ts.open_tournament(db, creator_id=ids[0], entry_fee=Decimal("1.00"), size=2)
        tid2 = t2.id
    # need a second, solvent user not already busy — reuse ids[1]
    async with SessionLocal() as db:
        await ts.join_tournament(db, tournament_id=tid2, user_id=ids[1])
    g2 = (await games_of(tid2))[0]
    try:
        async with SessionLocal() as db:
            await ts.report_game_by_faceit(
                db, faceit_match_id=g2.faceit_match_id, winner_faceit_id="not-a-player")
        check("bad winner faceit id rejected", False)
    except ts.TournamentError:
        check("bad winner faceit id rejected", True)

    print(f"\n=== {PASS} passed, {FAIL} failed ===")
    await engine.dispose()
    raise SystemExit(1 if FAIL else 0)


if __name__ == "__main__":
    asyncio.run(main())
