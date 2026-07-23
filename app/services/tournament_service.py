"""SpinCounter lifecycle: open -> join (until full) -> LOCK (wheel + bracket)
-> report games -> settle champion. Or cancel -> refund every entry.

A SpinCounter is a single-elimination 1v1 bracket. Every entry is one escrowed
buy-in, so an entry can never exist without money behind it — entries are only
written in the same DB transaction as their ESCROW debit, mirroring how table
seats work.

When the last seat fills, the bracket LOCKs in one transaction:
  * the prize pool is fixed (entry_fee * size, less rake),
  * the Wheel of Fortune spins once — a weighted-random segment picks a
    house-funded jackpot, awarded to a randomly-drawn entrant (BONUS credit,
    carrying rollover so it can't be cashed straight out),
  * seeds are drawn and the round-1 games are created.

Games are then reported one at a time; each winner advances into the next
round's slot, and when the final resolves the champion takes the pool. Every
money movement goes through `ledger`, and every mutation locks the tournament
row first (then user rows), the same concurrency discipline as match_service.
"""
import logging
import random
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import (
    SpinStatus,
    Tournament,
    TournamentEntry,
    TournamentGame,
    TransactionType,
    User,
)
from app.redis_client import link_faceit_game, resolve_faceit_game, set_match_state
from app.services import faceit, ledger

logger = logging.getLogger("spincounter")


class TournamentError(Exception):
    pass


def _is_power_of_two(n: int) -> bool:
    return n >= 2 and (n & (n - 1)) == 0


def _rounds_for(size: int) -> int:
    """Number of rounds a bracket of `size` players has. 4 -> 2, 8 -> 3."""
    r = 0
    while (1 << r) < size:
        r += 1
    return r


def _wins_needed(rounds_best_of: int) -> int:
    return rounds_best_of // 2 + 1


async def _entries(db: AsyncSession, tournament_id: int) -> list[TournamentEntry]:
    rows = (
        await db.execute(
            select(TournamentEntry)
            .where(TournamentEntry.tournament_id == tournament_id)
            .order_by(TournamentEntry.id)
        )
    ).scalars().all()
    return list(rows)


async def _games(db: AsyncSession, tournament_id: int) -> list[TournamentGame]:
    rows = (
        await db.execute(
            select(TournamentGame)
            .where(TournamentGame.tournament_id == tournament_id)
            .order_by(TournamentGame.round, TournamentGame.slot)
        )
    ).scalars().all()
    return list(rows)


async def _sync_state(db: AsyncSession, t: Tournament) -> None:
    """Best-effort volatile snapshot for fast reads — Postgres stays truth."""
    n = (
        await db.execute(
            select(func.count())
            .select_from(TournamentEntry)
            .where(TournamentEntry.tournament_id == t.id)
        )
    ).scalar_one()
    await set_match_state(
        # Namespaced away from table match-state so the two never collide.
        f"spin-{t.id}",
        {
            "status": t.status.value,
            "size": str(t.size),
            "entries": str(n),
        },
    )


# ─── open / join / leave ────────────────────────────────────────────────


async def open_tournament(
    db: AsyncSession,
    *,
    creator_id: int,
    entry_fee: Decimal,
    size: int,
    rounds_best_of: int | None = None,
) -> Tournament:
    """Open a PENDING SpinCounter and seat the creator (escrows their buy-in)."""
    if size not in settings.spin_sizes_list or not _is_power_of_two(size):
        raise TournamentError(f"unsupported bracket size: {size}")

    entry_fee = ledger.quantize(entry_fee)
    if entry_fee < settings.spin_min_entry or entry_fee > settings.spin_max_entry:
        raise TournamentError(
            f"entry fee must be between {settings.spin_min_entry} and "
            f"{settings.spin_max_entry}"
        )

    best_of = rounds_best_of or settings.spin_rounds_best_of
    if best_of < 1 or best_of % 2 == 0:
        raise TournamentError("rounds_best_of must be a positive odd number")

    creator = await ledger.lock_user(db, creator_id)
    if creator.balance < entry_fee:
        raise ledger.InsufficientFunds("insufficient balance for entry fee")

    t = Tournament(
        creator_id=creator_id,
        size=size,
        entry_fee=entry_fee,
        rounds_best_of=best_of,
        status=SpinStatus.PENDING,
    )
    db.add(t)
    await db.flush()  # assign t.id

    db.add(
        TournamentEntry(
            tournament_id=t.id, user_id=creator_id, contributed=entry_fee
        )
    )
    await ledger.debit(
        db, user=creator, tx_type=TransactionType.ESCROW, amount=entry_fee
    )

    await db.commit()
    await db.refresh(t)
    await _sync_state(db, t)
    return t


async def join_tournament(
    db: AsyncSession, *, tournament_id: int, user_id: int
) -> Tournament:
    """Take a bracket seat. Locks + spins the wheel once the last seat fills."""
    t = (
        await db.execute(
            select(Tournament)
            .where(Tournament.id == tournament_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if t is None:
        raise TournamentError("tournament not found")
    if t.status != SpinStatus.PENDING:
        raise TournamentError(f"tournament is {t.status.value}, cannot join")

    entries = await _entries(db, tournament_id)
    if any(e.user_id == user_id for e in entries):
        raise TournamentError("you are already in this tournament")
    if len(entries) >= t.size:
        raise TournamentError("this bracket is full")

    joiner = await ledger.lock_user(db, user_id)
    if joiner.balance < t.entry_fee:
        raise ledger.InsufficientFunds("insufficient balance for entry fee")

    db.add(
        TournamentEntry(
            tournament_id=t.id, user_id=user_id, contributed=t.entry_fee
        )
    )
    await ledger.debit(
        db, user=joiner, tx_type=TransactionType.ESCROW, amount=t.entry_fee
    )

    filled = len(entries) + 1 == t.size
    if filled:
        await _lock_and_start(db, t)

    try:
        await db.commit()
    except IntegrityError:
        # Lost the race on the unique (tournament_id, user_id) entry.
        await db.rollback()
        raise TournamentError("you are already in this tournament")
    await db.refresh(t)
    await _sync_state(db, t)
    # Escrow + lock are committed before any FACEIT call, so a FACEIT hiccup
    # can never un-escrow anyone — the round-1 games stay LIVE and are retried.
    if filled:
        await ensure_faceit_matches(db, t.id)
    return t


async def leave_tournament(
    db: AsyncSession, *, tournament_id: int, user_id: int
) -> Tournament:
    """Give up a seat while the bracket is still filling and take the buy-in back.

    Only while PENDING — once locked, the wheel has paid out and games are
    underway, so there is no clean unwind. The creator leaving cancels the whole
    tournament (refunding everyone) rather than orphaning it.
    """
    t = (
        await db.execute(
            select(Tournament)
            .where(Tournament.id == tournament_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if t is None:
        raise TournamentError("tournament not found")
    if t.status != SpinStatus.PENDING:
        raise TournamentError(f"tournament is {t.status.value}, cannot leave")
    if t.creator_id == user_id:
        return await cancel_and_refund(db, tournament_id=tournament_id, _locked=t)

    entry = (
        await db.execute(
            select(TournamentEntry).where(
                TournamentEntry.tournament_id == tournament_id,
                TournamentEntry.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if entry is None:
        raise TournamentError("you are not in this tournament")

    await _refund_entry(db, entry)
    await db.delete(entry)
    await db.commit()
    await db.refresh(t)
    await _sync_state(db, t)
    return t


async def _refund_entry(db: AsyncSession, entry: TournamentEntry) -> None:
    amount = entry.contributed
    if amount <= 0:
        return
    user = await ledger.lock_user(db, entry.user_id)
    await ledger.credit(db, user=user, tx_type=TransactionType.REFUND, amount=amount)


async def cancel_and_refund(
    db: AsyncSession, *, tournament_id: int, _locked: Tournament | None = None
) -> Tournament:
    """Refund every entry and mark CANCELLED. Idempotent-safe.

    Only meaningful before lock: once the bracket locks the wheel jackpot has
    been paid and the games have begun, so a locked/finished tournament is
    terminal here and returns unchanged.
    """
    t = _locked
    if t is None:
        t = (
            await db.execute(
                select(Tournament)
                .where(Tournament.id == tournament_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
    if t is None:
        raise TournamentError("tournament not found")
    if t.status != SpinStatus.PENDING:
        # LOCKED/LIVE/FINISHED/CANCELLED are all terminal for a refund: nothing
        # to unwind that this path may safely touch.
        return t

    for entry in await _entries(db, tournament_id):
        await _refund_entry(db, entry)

    t.status = SpinStatus.CANCELLED
    t.finished_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(t)
    await _sync_state(db, t)
    return t


# ─── lock: wheel + bracket ──────────────────────────────────────────────


def _spin_wheel() -> tuple[Decimal, int]:
    """Draw a weighted-random wheel segment. Returns (prize_amount, index)."""
    segments = settings.spin_wheel_list
    if not segments:
        return Decimal("0.00"), -1
    weights = [w for _, w in segments]
    index = random.choices(range(len(segments)), weights=weights, k=1)[0]
    return ledger.quantize(segments[index][0]), index


async def _lock_and_start(db: AsyncSession, t: Tournament) -> None:
    """Fix the pool, spin the wheel, draw seeds, create round-1 games.

    Runs inside the caller's open transaction (the final join), so the whole
    lock is atomic with the last escrow: a bracket never half-locks.
    """
    pool = ledger.quantize(t.entry_fee * t.size)
    t.rake_amount = ledger.quantize(pool * settings.spin_rake_fraction)
    t.prize_pool = ledger.quantize(pool - t.rake_amount)

    entries = await _entries(db, t.id)

    # ── Wheel of Fortune ──
    # House-funded promotional jackpot: a weighted-random segment picks the
    # amount, a random entrant wins it. It does NOT come from the pool (that is
    # why it can dwarf the buy-in) — in production its expected cost is a
    # marketing budget the segment weights tune. Credited as BONUS, raising the
    # winner's rollover so it can't be instantly withdrawn.
    prize, index = _spin_wheel()
    winner_entry = random.choice(entries)
    t.wheel_prize = prize
    t.wheel_segment_index = index
    t.wheel_winner_id = winner_entry.user_id
    if prize > 0:
        winner = await ledger.lock_user(db, winner_entry.user_id)
        await ledger.credit(
            db, user=winner, tx_type=TransactionType.BONUS, amount=prize
        )
        if settings.spin_wheel_rollover:
            ledger.raise_rollover(winner, prize)

    # ── Seed the bracket ──
    # Random seeding — no ELO ladder here, everyone paid the same to enter.
    order = list(entries)
    random.shuffle(order)
    for seed, entry in enumerate(order):
        entry.seed = seed

    # ── Create every game, empty above round 1, seeded in round 1 ──
    rounds = _rounds_for(t.size)
    for r in range(1, rounds + 1):
        games_in_round = t.size >> r  # size/2, size/4, ...
        for slot in range(games_in_round):
            game = TournamentGame(
                tournament_id=t.id,
                round=r,
                slot=slot,
                status=SpinStatus.PENDING,
            )
            if r == 1:
                # Seeds 2*slot vs 2*slot+1 meet in round 1.
                game.player_a_id = order[2 * slot].user_id
                game.player_b_id = order[2 * slot + 1].user_id
                game.status = SpinStatus.LIVE
            db.add(game)

    t.status = SpinStatus.LOCKED
    t.locked_at = datetime.now(timezone.utc)
    logger.info(
        "SpinCounter %s locked: pool %s, wheel %s to user %s",
        t.id,
        t.prize_pool,
        prize,
        winner_entry.user_id,
    )


# ─── report a game / advance the bracket / settle ───────────────────────


async def report_game(
    db: AsyncSession,
    *,
    tournament_id: int,
    game_id: int,
    winner_user_id: int,
    score_a: int | None = None,
    score_b: int | None = None,
) -> Tournament:
    """Record a game's result, advance the winner, and settle if it was the final.

    Idempotent on an already-finished game (returns unchanged). The tournament
    row is locked first so concurrent reports and advances serialize.
    """
    t = (
        await db.execute(
            select(Tournament)
            .where(Tournament.id == tournament_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if t is None:
        raise TournamentError("tournament not found")

    game = (
        await db.execute(
            select(TournamentGame).where(
                TournamentGame.id == game_id,
                TournamentGame.tournament_id == tournament_id,
            )
        )
    ).scalar_one_or_none()
    if game is None:
        raise TournamentError("game not found")
    # Idempotency FIRST, before the tournament-status gate: a duplicate
    # finished-webhook for the final arrives after the tournament is already
    # FINISHED, and must be a quiet no-op rather than an error.
    if game.status == SpinStatus.FINISHED:
        return t  # already reported
    if t.status not in (SpinStatus.LOCKED, SpinStatus.LIVE):
        raise TournamentError(f"tournament is {t.status.value}, cannot report")
    if game.player_a_id is None or game.player_b_id is None:
        raise TournamentError("this game's players are not both decided yet")
    if winner_user_id not in (game.player_a_id, game.player_b_id):
        raise TournamentError("reported winner is not in this game")

    wins = _wins_needed(t.rounds_best_of)
    if score_a is None or score_b is None:
        # Caller only told us the winner — synthesise a clean best-of score.
        if winner_user_id == game.player_a_id:
            score_a, score_b = wins, random.randint(0, wins - 1)
        else:
            score_a, score_b = random.randint(0, wins - 1), wins
    game.score_a = int(score_a)
    game.score_b = int(score_b)
    game.winner_id = winner_user_id
    game.status = SpinStatus.FINISHED
    game.finished_at = datetime.now(timezone.utc)

    loser_id = (
        game.player_b_id if winner_user_id == game.player_a_id else game.player_a_id
    )
    loser_entry = (
        await db.execute(
            select(TournamentEntry).where(
                TournamentEntry.tournament_id == tournament_id,
                TournamentEntry.user_id == loser_id,
            )
        )
    ).scalar_one_or_none()
    if loser_entry is not None:
        loser_entry.eliminated = True

    rounds = _rounds_for(t.size)
    if game.round >= rounds:
        # The final just resolved — winner is champion.
        await _settle(db, t, champion_id=winner_user_id)
    else:
        # Advance into the next round: round r slot s -> round r+1 slot s//2,
        # player A when s even, player B when s odd.
        nxt = (
            await db.execute(
                select(TournamentGame).where(
                    TournamentGame.tournament_id == tournament_id,
                    TournamentGame.round == game.round + 1,
                    TournamentGame.slot == game.slot // 2,
                )
            )
        ).scalar_one()
        if game.slot % 2 == 0:
            nxt.player_a_id = winner_user_id
        else:
            nxt.player_b_id = winner_user_id
        if nxt.player_a_id is not None and nxt.player_b_id is not None:
            nxt.status = SpinStatus.LIVE
        if t.status == SpinStatus.LOCKED:
            t.status = SpinStatus.LIVE

    await db.commit()
    await db.refresh(t)
    await _sync_state(db, t)
    return t


async def _settle(db: AsyncSession, t: Tournament, *, champion_id: int) -> None:
    """Pay the champion the prize pool and burn every entrant's rollover.

    The pool is 100% RTP by default (rake 0) — the whole buy-in pot goes to the
    champion. Every entrant played, so every entry burns its owner's rollover,
    losers included; this is the only place SpinCounter rollover burns, for the
    same reason matches burn at settle and not escrow.
    """
    champion = await ledger.lock_user(db, champion_id)
    payout = ledger.quantize(t.prize_pool)
    if payout > 0:
        await ledger.credit(
            db, user=champion, tx_type=TransactionType.WIN, amount=payout
        )

    for entry in await _entries(db, t.id):
        user = await ledger.lock_user(db, entry.user_id)
        ledger.burn_rollover(user, entry.contributed)

    t.champion_id = champion_id
    t.status = SpinStatus.FINISHED
    t.finished_at = datetime.now(timezone.utc)
    logger.info("SpinCounter %s settled: champion %s took %s", t.id, champion_id, payout)


# ─── FACEIT: one private match per bracket game ─────────────────────────


async def _faceit_ids(db: AsyncSession, user_ids: list[int]) -> dict[int, str]:
    rows = (
        await db.execute(
            select(User.id, User.faceit_id).where(User.id.in_(user_ids))
        )
    ).all()
    return {uid: fid for uid, fid in rows}


async def ensure_faceit_matches(db: AsyncSession, tournament_id: int) -> None:
    """Create a FACEIT private match for every ready game that lacks one.

    A bracket game is ready once both players are known (status LIVE). Each such
    game becomes its own 1v1 FACEIT match; the match id is stored on the game and
    linked in Redis so the webhook can resolve results back to it.

    Best-effort and idempotent: a game that already has a faceit_match_id is
    skipped, and a FACEIT failure leaves the game LIVE-without-id so a later call
    (next report, or a retry) can wire it up — it never blocks the bracket or
    touches escrow. No-op in demo mode, where the simulation reports games
    directly.
    """
    if settings.demo_mode:
        return
    games = (
        await db.execute(
            select(TournamentGame).where(
                TournamentGame.tournament_id == tournament_id,
                TournamentGame.status == SpinStatus.LIVE,
                TournamentGame.faceit_match_id.is_(None),
                TournamentGame.player_a_id.is_not(None),
                TournamentGame.player_b_id.is_not(None),
            )
        )
    ).scalars().all()
    if not games:
        return

    ids = {g.player_a_id for g in games} | {g.player_b_id for g in games}
    faceit_map = await _faceit_ids(db, list(ids))

    for game in games:
        a = faceit_map.get(game.player_a_id)
        b = faceit_map.get(game.player_b_id)
        if not a or not b:
            continue
        try:
            faceit_match_id = await faceit.create_private_match(
                [a], [b], match_ref=f"spin-{tournament_id}-g{game.id}"
            )
        except faceit.FaceitError:
            logger.exception(
                "FACEIT match creation failed for SpinCounter %s game %s",
                tournament_id,
                game.id,
            )
            continue
        game.faceit_match_id = faceit_match_id
        await db.commit()
        await link_faceit_game(faceit_match_id, tournament_id, game.id)


async def report_game_by_faceit(
    db: AsyncSession,
    *,
    faceit_match_id: str,
    winner_faceit_id: str,
    score_a: int | None = None,
    score_b: int | None = None,
) -> Tournament | None:
    """Settle the bracket game behind a FACEIT match (webhook entry point).

    Resolves the game (Redis first, then Postgres), maps the reported winning
    FACEIT id to the seat's user, and reports it. Returns None if the match is
    not one of ours. After advancing it wires up FACEIT for any newly-ready game.
    """
    resolved = await resolve_faceit_game(faceit_match_id)
    if resolved is None:
        row = (
            await db.execute(
                select(TournamentGame.tournament_id, TournamentGame.id).where(
                    TournamentGame.faceit_match_id == faceit_match_id
                )
            )
        ).first()
        if row is None:
            return None
        tournament_id, game_id = int(row[0]), int(row[1])
    else:
        tournament_id, game_id = resolved

    game = (
        await db.execute(
            select(TournamentGame).where(TournamentGame.id == game_id)
        )
    ).scalar_one_or_none()
    if game is None:
        return None
    winner_uid = None
    for uid in (game.player_a_id, game.player_b_id):
        if uid is None:
            continue
        fid = (
            await db.execute(select(User.faceit_id).where(User.id == uid))
        ).scalar_one_or_none()
        if fid == winner_faceit_id:
            winner_uid = uid
            break
    if winner_uid is None:
        raise TournamentError("reported winner is not in this bracket game")

    t = await report_game(
        db,
        tournament_id=tournament_id,
        game_id=game_id,
        winner_user_id=winner_uid,
        score_a=score_a,
        score_b=score_b,
    )
    # A win may have made the next round's game ready — wire its FACEIT match.
    await ensure_faceit_matches(db, tournament_id)
    return t


# ─── helpers for routers / demo ─────────────────────────────────────────


async def is_entrant(
    db: AsyncSession, *, tournament_id: int, user_id: int
) -> bool:
    n = (
        await db.execute(
            select(func.count())
            .select_from(TournamentEntry)
            .where(
                TournamentEntry.tournament_id == tournament_id,
                TournamentEntry.user_id == user_id,
            )
        )
    ).scalar_one()
    return bool(n)


async def next_playable_game(
    db: AsyncSession, tournament_id: int
) -> TournamentGame | None:
    """The lowest-round game that has both players and no winner yet."""
    return (
        await db.execute(
            select(TournamentGame)
            .where(
                TournamentGame.tournament_id == tournament_id,
                TournamentGame.status == SpinStatus.LIVE,
                TournamentGame.winner_id.is_(None),
            )
            .order_by(TournamentGame.round, TournamentGame.slot)
            .limit(1)
        )
    ).scalar_one_or_none()
