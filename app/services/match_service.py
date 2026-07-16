"""Table lifecycle: open -> join (until full, then LOCKED) -> settle / cancel.

A table is two sides of `team_size` seats. Every seat is one escrowed stake, so
the same code runs 1v1, 2v2 and 5v5 — only the seat count changes.

All money movement happens inside a single DB transaction per operation, and a
seat is only ever written in the same transaction as its ESCROW debit. So a
table can never hold a seat whose stake was not taken, or pay a winning side
without being marked FINISHED.
"""
import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import (
    Match,
    MatchParticipant,
    MatchStatus,
    Team,
    TransactionType,
    User,
)
from app.redis_client import link_faceit_match, set_match_state
from app.services import faceit, ledger

logger = logging.getLogger("match")


class MatchError(Exception):
    pass


async def _seats(db: AsyncSession, match_id: int) -> list[MatchParticipant]:
    rows = (
        await db.execute(
            select(MatchParticipant)
            .where(MatchParticipant.match_id == match_id)
            .order_by(MatchParticipant.id)
        )
    ).scalars().all()
    return list(rows)


def _seat_counts(seats: list[MatchParticipant]) -> dict[Team, int]:
    counts = {Team.A: 0, Team.B: 0}
    for s in seats:
        counts[s.team] += 1
    return counts


async def _sync_state(db: AsyncSession, match: Match) -> None:
    seats = await _seats(db, match.id)
    counts = _seat_counts(seats)
    await set_match_state(
        match.id,
        {
            "status": match.status.value,
            "team_size": str(match.team_size),
            "seats_a": str(counts[Team.A]),
            "seats_b": str(counts[Team.B]),
        },
    )


async def open_table(
    db: AsyncSession, *, creator_id: int, wager: Decimal, team_size: int
) -> Match:
    """Open a PENDING table and seat the creator on team A with their stake."""
    if team_size not in settings.allowed_team_sizes_list:
        raise MatchError(f"unsupported format: {team_size}v{team_size}")

    wager = ledger.quantize(wager)
    if wager < settings.min_wager or wager > settings.max_wager:
        raise MatchError(
            f"wager must be between {settings.min_wager} and {settings.max_wager}"
        )

    creator = await ledger.lock_user(db, creator_id)
    if creator.balance < wager:
        raise ledger.InsufficientFunds("insufficient balance for wager")

    match = Match(
        creator_id=creator_id,
        team_size=team_size,
        wager_amount=wager,
        pot_amount=Decimal("0.00"),
        rake_amount=Decimal("0.00"),
        status=MatchStatus.PENDING,
    )
    db.add(match)
    await db.flush()  # assign match.id

    db.add(
        MatchParticipant(
            match_id=match.id, user_id=creator_id, team=Team.A, contributed=wager
        )
    )
    await ledger.debit(
        db,
        user=creator,
        tx_type=TransactionType.ESCROW,
        amount=wager,
        match_id=match.id,
    )

    await db.commit()
    await db.refresh(match)
    await _sync_state(db, match)
    return match


async def join_table(
    db: AsyncSession, *, match_id: int, user_id: int, team: Team | None = None
) -> Match:
    """Take a seat: escrow the stake, and lock the table once every seat is filled.

    `team` picks a side; omitted, the emptier side is chosen so a lone joiner
    lands opposite the creator rather than next to them.
    """
    # Lock the table row to serialise concurrent joins against each other and
    # against cancel — two players must not be able to claim the last seat.
    match = (
        await db.execute(select(Match).where(Match.id == match_id).with_for_update())
    ).scalar_one_or_none()
    if match is None:
        raise MatchError("table not found")
    if match.status != MatchStatus.PENDING:
        raise MatchError(f"table is {match.status.value}, cannot join")

    seats = await _seats(db, match_id)
    if any(s.user_id == user_id for s in seats):
        raise MatchError("you are already at this table")

    counts = _seat_counts(seats)
    if team is None:
        team = Team.B if counts[Team.B] <= counts[Team.A] else Team.A
    if counts[team] >= match.team_size:
        raise MatchError(f"team {team.value} is full")

    joiner = await ledger.lock_user(db, user_id)
    wager = match.wager_amount
    if joiner.balance < wager:
        raise ledger.InsufficientFunds("insufficient balance for wager")

    db.add(
        MatchParticipant(
            match_id=match.id, user_id=user_id, team=team, contributed=wager
        )
    )
    await ledger.debit(
        db,
        user=joiner,
        tx_type=TransactionType.ESCROW,
        amount=wager,
        match_id=match.id,
    )

    counts[team] += 1
    filled = counts[Team.A] == match.team_size and counts[Team.B] == match.team_size
    if filled:
        pot = ledger.quantize(wager * 2 * match.team_size)
        match.pot_amount = pot
        match.rake_amount = ledger.quantize(pot * settings.rake_fraction)
        match.status = MatchStatus.LOCKED

    try:
        await db.commit()
    except IntegrityError:
        # Lost the race on the unique (match_id, user_id) seat.
        await db.rollback()
        raise MatchError("you are already at this table")
    await db.refresh(match)
    await _sync_state(db, match)

    if not filled:
        return match

    # Every stake is escrowed and the table is LOCKED. That state is committed
    # before the FACEIT call — a failure there must not un-escrow anyone (the
    # table can still be cancelled, which refunds).
    if settings.demo_mode:
        faceit_match_id = f"demo-{match.id}"
    else:
        rosters = await _rosters(db, match.id)
        try:
            faceit_match_id = await faceit.create_private_match(
                rosters[Team.A], rosters[Team.B], match_ref=f"wager-{match.id}"
            )
        except faceit.FaceitError:
            logger.exception("FACEIT match creation failed for table %s", match.id)
            # Stays LOCKED; an operator/cron can cancel -> refund if never started.
            raise MatchError("failed to create FACEIT match; stakes remain escrowed")

    match.faceit_match_id = faceit_match_id
    await db.commit()
    await db.refresh(match)
    await link_faceit_match(faceit_match_id, match.id)
    await set_match_state(match.id, {"faceit_match_id": faceit_match_id})
    return match


async def _rosters(db: AsyncSession, match_id: int) -> dict[Team, list[str]]:
    """FACEIT ids per side, for creating the private match."""
    rows = (
        await db.execute(
            select(MatchParticipant.team, User.faceit_id)
            .join(User, User.id == MatchParticipant.user_id)
            .where(MatchParticipant.match_id == match_id)
            .order_by(MatchParticipant.id)
        )
    ).all()
    out: dict[Team, list[str]] = {Team.A: [], Team.B: []}
    for team, faceit_id in rows:
        out[team].append(faceit_id)
    return out


async def leave_table(db: AsyncSession, *, match_id: int, user_id: int) -> Match:
    """Give up a seat on a still-filling table and take the stake back.

    Only while PENDING — once locked, the way out is cancel (refunds everyone).
    The creator leaving cancels the table outright rather than orphaning it.
    """
    match = (
        await db.execute(select(Match).where(Match.id == match_id).with_for_update())
    ).scalar_one_or_none()
    if match is None:
        raise MatchError("table not found")
    if match.status != MatchStatus.PENDING:
        raise MatchError(f"table is {match.status.value}, cannot leave")
    if match.creator_id == user_id:
        return await cancel_and_refund(db, match_id=match_id, _locked=match)

    seat = (
        await db.execute(
            select(MatchParticipant).where(
                MatchParticipant.match_id == match_id,
                MatchParticipant.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if seat is None:
        raise MatchError("you are not at this table")

    user = await ledger.lock_user(db, user_id)
    await ledger.credit(
        db,
        user=user,
        tx_type=TransactionType.REFUND,
        amount=match.wager_amount,
        match_id=match.id,
    )
    await db.delete(seat)

    await db.commit()
    await db.refresh(match)
    await _sync_state(db, match)
    return match


async def settle_finished(
    db: AsyncSession, *, match_id: int, winner_faceit_id: str
) -> Match:
    """Pay the reported winner's whole side (pot - rake, split). Idempotent-safe."""
    match = (
        await db.execute(select(Match).where(Match.id == match_id).with_for_update())
    ).scalar_one_or_none()
    if match is None:
        raise MatchError("table not found")
    if match.status == MatchStatus.FINISHED:
        return match  # already settled
    if match.status not in (MatchStatus.LOCKED, MatchStatus.LIVE):
        raise MatchError(f"cannot settle table in {match.status.value}")

    # FACEIT reports one winning player; their seat decides the winning side.
    rows = (
        await db.execute(
            select(
                MatchParticipant.user_id,
                MatchParticipant.team,
                MatchParticipant.contributed,
                User.faceit_id,
            )
            .join(User, User.id == MatchParticipant.user_id)
            .where(MatchParticipant.match_id == match_id)
            .order_by(MatchParticipant.id)
        )
    ).all()
    winning_team: Team | None = None
    for _uid, team, _c, faceit_id in rows:
        if faceit_id == winner_faceit_id:
            winning_team = team
            break
    if winning_team is None:
        raise MatchError("reported winner is not at this table")

    winner_ids = [uid for uid, team, _c, _f in rows if team == winning_team]
    payout_total = ledger.quantize(match.pot_amount - match.rake_amount)
    # Split evenly; any sub-cent remainder goes to the first seat so the credits
    # always sum to exactly payout_total.
    each = ledger.quantize(payout_total / len(winner_ids))
    remainder = payout_total - (each * len(winner_ids))

    for i, uid in enumerate(winner_ids):
        user = await ledger.lock_user(db, uid)
        await ledger.credit(
            db,
            user=user,
            tx_type=TransactionType.WIN,
            amount=each + (remainder if i == 0 else Decimal("0.00")),
            match_id=match.id,
        )

    # The match is played, so every stake at it counts toward its owner's
    # wagering requirement — losers included; they wagered too. This is the only
    # place rollover burns: crediting it at escrow would let a player open a
    # table, cancel for a refund, and clear the requirement having played
    # nothing.
    for uid, _team, contributed, _f in rows:
        user = await ledger.lock_user(db, uid)
        ledger.burn_rollover(user, contributed)

    match.winning_team = winning_team
    match.status = MatchStatus.FINISHED
    match.finished_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(match)
    await set_match_state(
        match.id, {"status": match.status.value, "winning_team": winning_team.value}
    )
    return match


async def cancel_and_refund(
    db: AsyncSession, *, match_id: int, _locked: Match | None = None
) -> Match:
    """Refund every seated stake and mark CANCELLED. Idempotent-safe.

    Refunds are driven off the seats, so a half-filled 5v5 returns exactly the
    stakes that were actually taken.
    """
    match = _locked
    if match is None:
        match = (
            await db.execute(
                select(Match).where(Match.id == match_id).with_for_update()
            )
        ).scalar_one_or_none()
    if match is None:
        raise MatchError("table not found")
    if match.status in (MatchStatus.CANCELLED, MatchStatus.FINISHED):
        return match  # terminal, nothing escrowed

    for seat in await _seats(db, match_id):
        user = await ledger.lock_user(db, seat.user_id)
        await ledger.credit(
            db,
            user=user,
            tx_type=TransactionType.REFUND,
            amount=match.wager_amount,
            match_id=match.id,
        )

    match.status = MatchStatus.CANCELLED
    match.finished_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(match)
    await set_match_state(match.id, {"status": match.status.value})
    return match


async def mark_live(db: AsyncSession, *, match_id: int) -> Match:
    match = (
        await db.execute(select(Match).where(Match.id == match_id).with_for_update())
    ).scalar_one_or_none()
    if match is None:
        raise MatchError("table not found")
    if match.status == MatchStatus.LOCKED:
        match.status = MatchStatus.LIVE
        await db.commit()
        await db.refresh(match)
        await set_match_state(match.id, {"status": match.status.value})
    return match


async def is_participant(db: AsyncSession, *, match_id: int, user_id: int) -> bool:
    n = (
        await db.execute(
            select(func.count())
            .select_from(MatchParticipant)
            .where(
                MatchParticipant.match_id == match_id,
                MatchParticipant.user_id == user_id,
            )
        )
    ).scalar_one()
    return bool(n)
