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
    Party,
    PartyLog,
    PartyLogKind,
    PartyMember,
    SplitMode,
    Team,
    TransactionType,
    User,
)
from app.redis_client import link_faceit_match, set_match_state
from app.services import faceit, ledger, party_service

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


async def _party_for_queue(
    db: AsyncSession, user_id: int
) -> tuple[Party, list[PartyMember]] | None:
    """The caller's party, locked, if they queue as one.

    A party of 1 queues as a solo player from their personal balance — the pool
    only comes into play once there's actually a team to fund. Only the leader
    may queue the party: seats and pool money for the whole group move on this
    call, and that authority is the leader's.
    """
    m = await party_service.membership(db, user_id)
    if m is None:
        return None
    members = await party_service.members_of(db, m.party_id)
    if len(members) < 2:
        return None
    party = (
        await db.execute(
            select(Party).where(Party.id == m.party_id).with_for_update()
        )
    ).scalar_one()
    if party.leader_id != user_id:
        raise MatchError("only the party leader can queue the party")
    return party, members


async def _seat_party(
    db: AsyncSession,
    match: Match,
    party: Party,
    members: list[PartyMember],
    team: Team,
) -> None:
    """Seat the whole party on one side, funded from the pool.

    The pool pays `wager × party_size`; each member's slice is drained from
    their entitlement proportionally, so a sponsor's seat costs the sponsor and
    a free-rider's seat costs them nothing. That per-member slice is written to
    the seat as `contributed` — it is what the payout split and the rollover
    burn will later be computed from, so asymmetric funding flows through the
    whole lifecycle from this one allocation.
    """
    total = ledger.quantize(match.wager_amount * len(members))
    if party.pool_balance < total:
        raise MatchError(
            f"team balance {party.pool_balance} cannot cover the {total} buy-in"
        )
    shares = party_service.allocate(
        total, [(m.user_id, m.entitlement) for m in members]
    )
    for m in members:
        share = shares[m.user_id]
        m.entitlement = ledger.quantize(m.entitlement - share)
        db.add(
            MatchParticipant(
                match_id=match.id,
                user_id=m.user_id,
                team=team,
                contributed=share,
                party_id=party.id,
                party_split=party.split_mode,
            )
        )
        db.add(
            PartyLog(
                party_id=party.id,
                user_id=m.user_id,
                kind=PartyLogKind.ESCROW,
                amount=share,
                match_id=match.id,
            )
        )
    party.pool_balance = ledger.quantize(party.pool_balance - total)


async def open_table(
    db: AsyncSession, *, creator_id: int, wager: Decimal, team_size: int
) -> Match:
    """Open a PENDING table; the creator (or their whole party) takes team A.

    A party can only queue formats it fits into: team_size >= party size. So a
    duo sees 2v2 and 5v5, a full five sees only 5v5 — the guarantee is that the
    party is never split across sides or tables.
    """
    if team_size not in settings.allowed_team_sizes_list:
        raise MatchError(f"unsupported format: {team_size}v{team_size}")

    wager = ledger.quantize(wager)
    if wager < settings.min_wager or wager > settings.max_wager:
        raise MatchError(
            f"wager must be between {settings.min_wager} and {settings.max_wager}"
        )

    try:
        party_ctx = await _party_for_queue(db, creator_id)
    except party_service.PartyError as exc:
        raise MatchError(str(exc))
    if party_ctx and team_size < len(party_ctx[1]):
        raise MatchError(
            f"a party of {len(party_ctx[1])} does not fit in {team_size}v{team_size}"
        )

    creator = None
    if party_ctx is None:
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

    if party_ctx is not None:
        party, members = party_ctx
        await _seat_party(db, match, party, members, Team.A)
    else:
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

    try:
        party_ctx = await _party_for_queue(db, user_id)
    except party_service.PartyError as exc:
        raise MatchError(str(exc))
    group = [m.user_id for m in party_ctx[1]] if party_ctx else [user_id]

    seated_ids = {s.user_id for s in seats}
    if any(uid in seated_ids for uid in group):
        raise MatchError("you are already at this table")

    counts = _seat_counts(seats)
    need = len(group)
    if team is None:
        # The emptier side that actually fits the whole group; ties go to B so
        # a joiner lands opposite the creator rather than next to them.
        candidates = [
            t
            for t in (Team.B, Team.A)
            if match.team_size - counts[t] >= need
        ]
        if not candidates:
            raise MatchError(
                f"no side has {need} open seats for your party"
            )
        team = min(candidates, key=lambda t: counts[t])
    if match.team_size - counts[team] < need:
        raise MatchError(
            f"team {team.value} does not have {need} open seats"
        )

    wager = match.wager_amount
    if party_ctx is not None:
        party, members = party_ctx
        await _seat_party(db, match, party, members, team)
    else:
        joiner = await ledger.lock_user(db, user_id)
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

    counts[team] += need
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


async def _refund_seat(
    db: AsyncSession, match: Match, seat: MatchParticipant
) -> None:
    """Return a seat's funding to its source: the player, or the party pool.

    If the party (or the member's place in it) is gone by the time the refund
    lands, the money goes to the player personally — it must never strand in a
    pool the funder can no longer reach.
    """
    amount = seat.contributed
    if amount <= 0:
        return
    if seat.party_id is not None:
        party = (
            await db.execute(
                select(Party)
                .where(Party.id == seat.party_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if party is not None:
            member = (
                await db.execute(
                    select(PartyMember).where(
                        PartyMember.party_id == seat.party_id,
                        PartyMember.user_id == seat.user_id,
                    )
                )
            ).scalar_one_or_none()
            if member is not None:
                party.pool_balance = ledger.quantize(party.pool_balance + amount)
                member.entitlement = ledger.quantize(member.entitlement + amount)
                db.add(
                    PartyLog(
                        party_id=party.id,
                        user_id=seat.user_id,
                        kind=PartyLogKind.REFUND,
                        amount=amount,
                        match_id=match.id,
                    )
                )
                return
    user = await ledger.lock_user(db, seat.user_id)
    await ledger.credit(
        db,
        user=user,
        tx_type=TransactionType.REFUND,
        amount=amount,
        match_id=match.id,
    )


async def leave_table(db: AsyncSession, *, match_id: int, user_id: int) -> Match:
    """Give up seats on a still-filling table and take the funding back.

    Only while PENDING — once locked, the way out is cancel (refunds everyone).
    The creator leaving cancels the table outright rather than orphaning it.
    Party seats move together: the leader pulls the whole party out, and a
    member can't abandon a seat someone else's pool money is holding.
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

    if seat.party_id is not None:
        party = (
            await db.execute(
                select(Party).where(Party.id == seat.party_id)
            )
        ).scalar_one_or_none()
        if party is not None and party.leader_id != user_id:
            raise MatchError(
                "party seats leave together — your leader can pull the party out"
            )
        # The leader takes every seat the party queued with them.
        party_seats = (
            await db.execute(
                select(MatchParticipant).where(
                    MatchParticipant.match_id == match_id,
                    MatchParticipant.party_id == seat.party_id,
                )
            )
        ).scalars().all()
        for s in party_seats:
            await _refund_seat(db, match, s)
            await db.delete(s)
    else:
        await _refund_seat(db, match, seat)
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
                MatchParticipant.party_id,
                MatchParticipant.party_split,
                User.faceit_id,
            )
            .join(User, User.id == MatchParticipant.user_id)
            .where(MatchParticipant.match_id == match_id)
            .order_by(MatchParticipant.id)
        )
    ).all()
    winning_team: Team | None = None
    for r in rows:
        if r.faceit_id == winner_faceit_id:
            winning_team = r.team
            break
    if winning_team is None:
        raise MatchError("reported winner is not at this table")

    winners = [r for r in rows if r.team == winning_team]
    payout_total = ledger.quantize(match.pot_amount - match.rake_amount)
    # Split by what each seat actually FUNDED, not per head. Solo seats all
    # funded one stake so this stays an even split; a party's asymmetric
    # funding pays out asymmetrically — put in 20% of your side's buy-in, take
    # 20% of the pot. A sponsored free-rider funded nothing and receives
    # nothing here (the leader can gift them from the pool afterwards, capped).
    shares = party_service.allocate(
        payout_total, [(r.user_id, r.contributed) for r in winners]
    )

    # LEADER-mode party seats bank their winnings in the party pool instead of
    # being paid out; each member's entitlement rises by their proportional
    # share, which caps what the leader may later pay whom. The split mode was
    # snapshotted onto the seat at escrow, so flipping the toggle after the
    # result changes nothing about this match.
    parties: dict[int, Party] = {}
    for r in winners:
        share = shares[r.user_id]
        banked = False
        if r.party_split == SplitMode.LEADER and r.party_id is not None:
            if r.party_id not in parties:
                parties[r.party_id] = (
                    await db.execute(
                        select(Party)
                        .where(Party.id == r.party_id)
                        .with_for_update()
                    )
                ).scalar_one_or_none()
            party = parties[r.party_id]
            if party is not None:
                member = (
                    await db.execute(
                        select(PartyMember).where(
                            PartyMember.party_id == r.party_id,
                            PartyMember.user_id == r.user_id,
                        )
                    )
                ).scalar_one_or_none()
                if member is not None:
                    party.pool_balance = ledger.quantize(
                        party.pool_balance + share
                    )
                    member.entitlement = ledger.quantize(
                        member.entitlement + share
                    )
                    db.add(
                        PartyLog(
                            party_id=party.id,
                            user_id=r.user_id,
                            kind=PartyLogKind.WIN,
                            amount=share,
                            match_id=match.id,
                        )
                    )
                    banked = True
        # Personal payout — solo seats, proportional-mode parties, and the
        # fallback for anyone whose party dissolved mid-match: their share is
        # theirs, it must not strand in a pool they can no longer reach.
        if not banked and share > 0:
            user = await ledger.lock_user(db, r.user_id)
            await ledger.credit(
                db,
                user=user,
                tx_type=TransactionType.WIN,
                amount=share,
                match_id=match.id,
            )

    # The match is played, so every stake at it counts toward its owner's
    # wagering requirement — losers included; they wagered too. This is the only
    # place rollover burns: crediting it at escrow would let a player open a
    # table, cancel for a refund, and clear the requirement having played
    # nothing.
    for r in rows:
        user = await ledger.lock_user(db, r.user_id)
        ledger.burn_rollover(user, r.contributed)

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

    # Refund what each seat actually FUNDED, back to where it came from: solo
    # stakes to the player, pool-funded slices to the party pool (and the
    # member's entitlement). A sponsor gets their whole sponsorship back; a
    # free-rider funded nothing and is owed nothing.
    for seat in await _seats(db, match_id):
        await _refund_seat(db, match, seat)

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
