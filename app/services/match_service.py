"""Match lifecycle: create -> accept (LOCKED) -> settle / cancel.

All money movement happens inside a single DB transaction per operation so a
match can never end up with one player escrowed and the other not, or a winner
credited without the match marked FINISHED.
"""
import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Match, MatchStatus, TransactionType, User
from app.redis_client import link_faceit_match, set_match_state
from app.services import faceit, ledger

logger = logging.getLogger("match")


class MatchError(Exception):
    pass


async def create_match(
    db: AsyncSession, *, challenger_id: int, wager: Decimal
) -> Match:
    """Create an open PENDING match and escrow the challenger's stake.

    No opponent is chosen up front — the match waits for any player to accept
    (see accept_match), at which point their stake is escrowed too.
    """
    wager = ledger.quantize(wager)
    if wager < settings.min_wager or wager > settings.max_wager:
        raise MatchError(
            f"wager must be between {settings.min_wager} and {settings.max_wager}"
        )

    # Lock challenger and escrow their stake.
    challenger = await ledger.lock_user(db, challenger_id)
    if challenger.balance < wager:
        raise ledger.InsufficientFunds("insufficient balance for wager")

    match = Match(
        player1_id=challenger_id,
        player2_id=None,
        wager_amount=wager,
        pot_amount=Decimal("0.00"),
        rake_amount=Decimal("0.00"),
        status=MatchStatus.PENDING,
    )
    db.add(match)
    await db.flush()  # assign match.id

    await ledger.debit(
        db,
        user=challenger,
        tx_type=TransactionType.ESCROW,
        amount=wager,
        match_id=match.id,
    )

    await db.commit()
    await db.refresh(match)
    await set_match_state(
        match.id, {"status": match.status.value, "escrowed": "p1"}
    )
    return match


async def accept_match(db: AsyncSession, *, match_id: int, opponent_id: int) -> Match:
    """Opponent accepts: escrow their stake, lock the match, create FACEIT match."""
    # Lock the match row to serialize accept/cancel.
    match = (
        await db.execute(
            select(Match).where(Match.id == match_id).with_for_update()
        )
    ).scalar_one_or_none()
    if match is None:
        raise MatchError("match not found")
    if match.status != MatchStatus.PENDING:
        raise MatchError(f"match is {match.status.value}, cannot accept")
    if match.player2_id is not None:
        raise MatchError("match already has an opponent")
    if match.player1_id == opponent_id:
        raise MatchError("cannot accept your own match")

    opponent = await ledger.lock_user(db, opponent_id)
    wager = match.wager_amount
    if opponent.balance < wager:
        raise ledger.InsufficientFunds("insufficient balance for wager")

    await ledger.debit(
        db,
        user=opponent,
        tx_type=TransactionType.ESCROW,
        amount=wager,
        match_id=match.id,
    )

    match.player2_id = opponent_id
    pot = ledger.quantize(wager * 2)
    rake = ledger.quantize(pot * settings.rake_fraction)
    match.pot_amount = pot
    match.rake_amount = rake
    match.status = MatchStatus.LOCKED

    # Both stakes are now escrowed and the match is LOCKED. Commit the money
    # state first; a failure creating the FACEIT match must not un-escrow funds
    # (the match can still be cancelled -> refunded).
    await db.commit()
    await db.refresh(match)
    await set_match_state(
        match.id, {"status": match.status.value, "escrowed": "both"}
    )

    # Create the private FACEIT match (external call, outside the money txn).
    if settings.demo_mode:
        # Demo: no real FACEIT call — synthesize a match id.
        faceit_match_id = f"demo-{match.id}"
    else:
        p1 = (
            await db.execute(select(User).where(User.id == match.player1_id))
        ).scalar_one()
        p2 = (
            await db.execute(select(User).where(User.id == match.player2_id))
        ).scalar_one()
        try:
            faceit_match_id = await faceit.create_private_match(
                p1.faceit_id, p2.faceit_id, match_ref=f"wager-{match.id}"
            )
        except faceit.FaceitError:
            logger.exception("FACEIT match creation failed for match %s", match.id)
            # Leave LOCKED; an operator/cron can cancel -> refund if never started.
            raise MatchError(
                "failed to create FACEIT match; wager remains escrowed"
            )

    match.faceit_match_id = faceit_match_id
    await db.commit()
    await db.refresh(match)
    await link_faceit_match(faceit_match_id, match.id)
    await set_match_state(match.id, {"faceit_match_id": faceit_match_id})
    return match


async def settle_finished(
    db: AsyncSession, *, match_id: int, winner_faceit_id: str
) -> Match:
    """Credit the winner (pot - rake) and mark FINISHED. Idempotent-safe."""
    from datetime import datetime, timezone

    match = (
        await db.execute(
            select(Match).where(Match.id == match_id).with_for_update()
        )
    ).scalar_one_or_none()
    if match is None:
        raise MatchError("match not found")
    if match.status == MatchStatus.FINISHED:
        return match  # already settled
    if match.status not in (MatchStatus.LOCKED, MatchStatus.LIVE):
        raise MatchError(f"cannot settle match in {match.status.value}")

    # Map the reported FACEIT winner to one of our two players.
    p1 = await ledger.lock_user(db, match.player1_id)
    p2 = await ledger.lock_user(db, match.player2_id)
    if winner_faceit_id == p1.faceit_id:
        winner = p1
    elif winner_faceit_id == p2.faceit_id:
        winner = p2
    else:
        raise MatchError("reported winner is not a participant")

    payout = ledger.quantize(match.pot_amount - match.rake_amount)
    await ledger.credit(
        db,
        user=winner,
        tx_type=TransactionType.WIN,
        amount=payout,
        match_id=match.id,
    )

    match.winner_id = winner.id
    match.status = MatchStatus.FINISHED
    match.finished_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(match)
    await set_match_state(
        match.id, {"status": match.status.value, "winner_id": str(winner.id)}
    )
    return match


async def cancel_and_refund(db: AsyncSession, *, match_id: int) -> Match:
    """Refund both players' escrow and mark CANCELLED. Idempotent-safe."""
    from datetime import datetime, timezone

    match = (
        await db.execute(
            select(Match).where(Match.id == match_id).with_for_update()
        )
    ).scalar_one_or_none()
    if match is None:
        raise MatchError("match not found")
    if match.status in (MatchStatus.CANCELLED, MatchStatus.FINISHED):
        return match  # nothing to refund / already terminal

    wager = match.wager_amount

    # Player 1 is always escrowed (at create). Player 2 only if LOCKED/LIVE.
    p1 = await ledger.lock_user(db, match.player1_id)
    await ledger.credit(
        db,
        user=p1,
        tx_type=TransactionType.REFUND,
        amount=wager,
        match_id=match.id,
    )
    if match.status in (MatchStatus.LOCKED, MatchStatus.LIVE):
        p2 = await ledger.lock_user(db, match.player2_id)
        await ledger.credit(
            db,
            user=p2,
            tx_type=TransactionType.REFUND,
            amount=wager,
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
        await db.execute(
            select(Match).where(Match.id == match_id).with_for_update()
        )
    ).scalar_one_or_none()
    if match is None:
        raise MatchError("match not found")
    if match.status == MatchStatus.LOCKED:
        match.status = MatchStatus.LIVE
        await db.commit()
        await db.refresh(match)
        await set_match_state(match.id, {"status": match.status.value})
    return match
