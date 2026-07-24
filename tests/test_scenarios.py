"""End-to-end scenario harness for SpinCounter, run against a fresh SQLite DB.

Mirrors how the app actually uses the DB: a fresh session per operation. Works
in primitive ids, re-querying fresh each time, so nothing is held across a
commit/rollback. Asserts money conservation, bracket correctness and every
error path. Run:

    DATABASE_URL="sqlite+aiosqlite:///./scen.db" REDIS_ENABLED=false \
        DEMO_MODE=false PYTHONPATH=. python3 scratchpad/scenarios.py
"""
import asyncio
from decimal import Decimal

from sqlalchemy import select

from app.database import Base, SessionLocal, engine
from app.models import (
    SpinStatus,
    Tournament,
    TournamentEntry,
    TournamentGame,
    Transaction,
    TransactionType,
    User,
)
from app.services import ledger, tournament_service as ts

PASS, FAIL = 0, 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}")


async def mkuser(name, bal="100.00"):
    async with SessionLocal() as db:
        u = User(
            faceit_id=f"fid-{name}",
            faceit_username=name,
            faceit_elo=1000,
            balance=Decimal(bal),
            is_verified=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id


async def uget(uid, attr):
    async with SessionLocal() as db:
        u = (await db.execute(select(User).where(User.id == uid))).scalar_one()
        return getattr(u, attr)


async def bal(uid):
    return await uget(uid, "balance")


async def tget(tid):
    async with SessionLocal() as db:
        return (
            await db.execute(select(Tournament).where(Tournament.id == tid))
        ).scalar_one()


async def games_of(tid):
    async with SessionLocal() as db:
        return (
            await db.execute(
                select(TournamentGame)
                .where(TournamentGame.tournament_id == tid)
                .order_by(TournamentGame.round, TournamentGame.slot)
            )
        ).scalars().all()


async def entries_of(tid):
    async with SessionLocal() as db:
        return (
            await db.execute(
                select(TournamentEntry).where(TournamentEntry.tournament_id == tid)
            )
        ).scalars().all()


async def open_t(creator_id, fee, size):
    async with SessionLocal() as db:
        t = await ts.open_tournament(
            db, creator_id=creator_id, entry_fee=Decimal(fee), size=size
        )
        return t.id


async def join_t(tid, uid):
    async with SessionLocal() as db:
        await ts.join_tournament(db, tournament_id=tid, user_id=uid)


async def total_balance(uids):
    tot = Decimal("0.00")
    for uid in uids:
        tot += await bal(uid)
    return tot


async def play_to_champion(tid):
    """Report every live game (player_a always wins) until the bracket ends."""
    while True:
        async with SessionLocal() as db:
            g = await ts.next_playable_game(db, tid)
            if g is None:
                break
            await ts.report_game(
                db, tournament_id=tid, game_id=g.id, winner_user_id=g.player_a_id
            )


async def scenario_happy_4():
    print("\n[Scenario] 4-player bracket: full lifecycle + money conservation")
    ids = [await mkuser(f"h4_{i}", "100.00") for i in range(4)]
    start_total = await total_balance(ids)

    tid = await open_t(ids[0], "3.00", 4)
    check("creator escrowed 3", await bal(ids[0]) == Decimal("97.00"))
    for uid in ids[1:]:
        await join_t(tid, uid)

    t = await tget(tid)
    check("locked when full", t.status == SpinStatus.LOCKED)
    check("prize pool = 4*3 = 12", t.prize_pool == Decimal("12.00"))
    check("wheel winner assigned", t.wheel_winner_id in ids)
    check("wheel prize > 0", t.wheel_prize > 0)

    games = await games_of(tid)
    check("4-player bracket has 3 games (2 semi + 1 final)", len(games) == 3)
    r1 = [g for g in games if g.round == 1]
    check("2 semifinals seeded LIVE", len(r1) == 2 and all(g.status == SpinStatus.LIVE for g in r1))
    finals = [g for g in games if g.round == 2]
    check("final has no players yet", finals[0].player_a_id is None and finals[0].player_b_id is None)

    wheel_winner = t.wheel_winner_id
    wheel_prize = t.wheel_prize

    await play_to_champion(tid)
    t = await tget(tid)
    check("tournament FINISHED", t.status == SpinStatus.FINISHED)
    check("champion set", t.champion_id in ids)

    end_total = await total_balance(ids)
    expected = start_total - Decimal("12.00") + Decimal("12.00") + wheel_prize
    check(f"money conserved (pool RTP + house wheel {wheel_prize})", end_total == expected)

    expected_champ = Decimal("100.00") - Decimal("3.00") + Decimal("12.00")
    if t.champion_id == wheel_winner:
        expected_champ += wheel_prize
    check("champion balance exact", await bal(t.champion_id) == expected_champ)


async def scenario_size2():
    print("\n[Scenario] 2-player bracket: single final")
    a = await mkuser("s2a"); b = await mkuser("s2b")
    tid = await open_t(a, "5.00", 2)
    await join_t(tid, b)
    t = await tget(tid)
    check("size-2 locks on 2nd join", t.status == SpinStatus.LOCKED)
    games = await games_of(tid)
    check("size-2 has exactly 1 game (the final)", len(games) == 1 and games[0].round == 1)
    await play_to_champion(tid)
    t = await tget(tid)
    check("size-2 finishes", t.status == SpinStatus.FINISHED)
    check("size-2 prize pool = 10", t.prize_pool == Decimal("10.00"))


async def scenario_size8():
    print("\n[Scenario] 8-player bracket: quarters -> semis -> final")
    ids = [await mkuser(f"e8_{i}") for i in range(8)]
    tid = await open_t(ids[0], "5.00", 8)
    for uid in ids[1:]:
        await join_t(tid, uid)
    games = await games_of(tid)
    by_round = {}
    for g in games:
        by_round.setdefault(g.round, []).append(g)
    check("8-player: round1 has 4 games", len(by_round[1]) == 4)
    check("8-player: round2 has 2 games", len(by_round[2]) == 2)
    check("8-player: round3 has 1 game", len(by_round[3]) == 1)
    check("8-player: 7 games total", len(games) == 7)
    await play_to_champion(tid)
    t = await tget(tid)
    check("8-player finishes with champion", t.status == SpinStatus.FINISHED and t.champion_id is not None)
    check("8-player prize pool = 40", t.prize_pool == Decimal("40.00"))


async def expect_error(coro, exc, label):
    try:
        await coro
        check(label, False)
    except exc:
        check(label, True)


async def scenario_errors():
    print("\n[Scenario] Error paths")
    poor = await mkuser("err_poor", "2.00")
    async with SessionLocal() as db:
        await expect_error(
            ts.open_tournament(db, creator_id=poor, entry_fee=Decimal("3.00"), size=4),
            ledger.InsufficientFunds, "insufficient funds raises")

    rich = await mkuser("err_rich", "100.00")
    async with SessionLocal() as db:
        await expect_error(
            ts.open_tournament(db, creator_id=rich, entry_fee=Decimal("3.00"), size=3),
            ts.TournamentError, "non-power-of-two size rejected")
    async with SessionLocal() as db:
        await expect_error(
            ts.open_tournament(db, creator_id=rich, entry_fee=Decimal("0.50"), size=4),
            ts.TournamentError, "below-min entry rejected")
    check("rejected creator never charged", await bal(rich) == Decimal("100.00"))

    c = await mkuser("err_c")
    tid = await open_t(c, "3.00", 4)
    async with SessionLocal() as db:
        await expect_error(
            ts.join_tournament(db, tournament_id=tid, user_id=c),
            ts.TournamentError, "double-join rejected")

    ids = [await mkuser(f"full_{i}") for i in range(4)]
    ftid = await open_t(ids[0], "3.00", 4)
    for uid in ids[1:]:
        await join_t(ftid, uid)
    extra = await mkuser("full_extra")
    async with SessionLocal() as db:
        await expect_error(
            ts.join_tournament(db, tournament_id=ftid, user_id=extra),
            ts.TournamentError, "join full bracket rejected")
    check("extra player not charged", await bal(extra) == Decimal("100.00"))


async def scenario_leave_cancel():
    print("\n[Scenario] Leave / cancel refunds")
    a = await mkuser("lc_a"); b = await mkuser("lc_b")
    tid = await open_t(a, "10.00", 4)
    await join_t(tid, b)
    check("b escrowed 10", await bal(b) == Decimal("90.00"))
    async with SessionLocal() as db:
        await ts.leave_tournament(db, tournament_id=tid, user_id=b)
    check("b refunded on leave", await bal(b) == Decimal("100.00"))
    check("b's entry removed", all(e.user_id != b for e in await entries_of(tid)))

    c = await mkuser("lc_c")
    await join_t(tid, c)
    async with SessionLocal() as db:
        await ts.leave_tournament(db, tournament_id=tid, user_id=a)  # creator
    t = await tget(tid)
    check("creator leave cancels tournament", t.status == SpinStatus.CANCELLED)
    check("creator refunded", await bal(a) == Decimal("100.00"))
    check("remaining entrant refunded", await bal(c) == Decimal("100.00"))

    async with SessionLocal() as db:
        t2 = await ts.cancel_and_refund(db, tournament_id=tid)
    check("cancel idempotent (still cancelled)", t2.status == SpinStatus.CANCELLED)
    check("no double refund", await bal(a) == Decimal("100.00"))


async def scenario_locked_guards():
    print("\n[Scenario] Post-lock guards")
    ids = [await mkuser(f"lg_{i}") for i in range(4)]
    tid = await open_t(ids[0], "3.00", 4)
    for uid in ids[1:]:
        await join_t(tid, uid)
    async with SessionLocal() as db:
        await expect_error(
            ts.leave_tournament(db, tournament_id=tid, user_id=ids[1]),
            ts.TournamentError, "leave after lock rejected")
    b_before = await bal(ids[1])
    async with SessionLocal() as db:
        t2 = await ts.cancel_and_refund(db, tournament_id=tid)
    check("cancel after lock does not refund", await bal(ids[1]) == b_before)
    check("cancel after lock leaves it LOCKED", t2.status == SpinStatus.LOCKED)


async def scenario_report_guards():
    print("\n[Scenario] report_game guards + idempotency")
    ids = [await mkuser(f"rg_{i}") for i in range(4)]
    tid = await open_t(ids[0], "3.00", 4)
    for uid in ids[1:]:
        await join_t(tid, uid)
    games = await games_of(tid)
    semi1 = games[0]
    final = [g for g in games if g.round == 2][0]

    async with SessionLocal() as db:
        await expect_error(
            ts.report_game(db, tournament_id=tid, game_id=final.id, winner_user_id=semi1.player_a_id),
            ts.TournamentError, "report final before players rejected")
    async with SessionLocal() as db:
        await expect_error(
            ts.report_game(db, tournament_id=tid, game_id=semi1.id, winner_user_id=999999),
            ts.TournamentError, "report with non-participant winner rejected")

    async with SessionLocal() as db:
        await ts.report_game(db, tournament_id=tid, game_id=semi1.id, winner_user_id=semi1.player_a_id)
    games2 = await games_of(tid)
    final2 = [g for g in games2 if g.round == 2][0]
    check("semi1 winner advances into final slot A", final2.player_a_id == semi1.player_a_id)

    async with SessionLocal() as db:
        await ts.report_game(db, tournament_id=tid, game_id=semi1.id, winner_user_id=semi1.player_b_id)
    games3 = await games_of(tid)
    semi1r = [g for g in games3 if g.id == semi1.id][0]
    check("re-report of finished game is a no-op", semi1r.winner_id == semi1.player_a_id)

    loser = semi1.player_b_id
    le = [e for e in await entries_of(tid) if e.user_id == loser][0]
    check("semi loser eliminated", le.eliminated is True)


async def scenario_rollover():
    print("\n[Scenario] Rollover: entries burn at settle, wheel bonus raises it")
    ids = [await mkuser(f"ro_{i}") for i in range(4)]
    for uid in ids:
        async with SessionLocal() as db:
            u = await ledger.lock_user(db, uid)
            ledger.raise_rollover(u, Decimal("50.00"))
            await db.commit()

    tid = await open_t(ids[0], "3.00", 4)
    for uid in ids[1:]:
        await join_t(tid, uid)
    t = await tget(tid)
    wheel_winner, wheel_prize = t.wheel_winner_id, t.wheel_prize
    check("wheel winner rollover raised by prize",
          await uget(wheel_winner, "rollover_requirement") == Decimal("50.00") + wheel_prize)

    await play_to_champion(tid)
    for uid in ids:
        ro = await uget(uid, "rollover_requirement")
        base = Decimal("50.00") - Decimal("3.00")
        if uid == wheel_winner:
            base += wheel_prize
        check(f"user {uid} rollover burned by entry stake", ro == base)


async def scenario_bonus_ledger():
    print("\n[Scenario] Wheel bonus writes exactly one BONUS transaction")
    ids = [await mkuser(f"bl_{i}") for i in range(4)]
    tid = await open_t(ids[0], "3.00", 4)
    for uid in ids[1:]:
        await join_t(tid, uid)
    t = await tget(tid)
    async with SessionLocal() as db:
        rows = (await db.execute(
            select(Transaction).where(
                Transaction.user_id == t.wheel_winner_id,
                Transaction.type == TransactionType.BONUS,
            )
        )).scalars().all()
    check("exactly one BONUS tx for wheel winner",
          len(rows) == 1 and rows[0].amount == t.wheel_prize)


async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await scenario_happy_4()
    await scenario_size2()
    await scenario_size8()
    await scenario_errors()
    await scenario_leave_cancel()
    await scenario_locked_guards()
    await scenario_report_guards()
    await scenario_rollover()
    await scenario_bonus_ledger()
    print(f"\n=== {PASS} passed, {FAIL} failed ===")
    await engine.dispose()
    raise SystemExit(1 if FAIL else 0)


if __name__ == "__main__":
    asyncio.run(main())
