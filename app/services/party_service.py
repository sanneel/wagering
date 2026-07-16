"""Parties: transient teams with a pooled balance (the Team Balance).

Money model
-----------
The pool is funded from members' personal balances (contribute) and pays for
the party's seats when it queues. Each member holds an `entitlement` — their
proportional claim on the pool:

    contribute X          entitlement +X   (it's their money)
    pool escrows a match  entitlements drained proportionally; each member's
                          drain is recorded as their seat's `contributed`
    winnings banked       entitlement raised by each member's proportional
    (LEADER mode)         share of the win

`pool_balance == sum(entitlements)` always.

Why entitlements exist: they are the anti-laundering cap on "Leader Decides".
A leader may pay a member up to that member's entitlement freely — that is the
member's own money / own share coming back. Anything above it must come out of
the LEADER's entitlement, and that gifted slice raises the recipient's rollover
requirement — so a gift can be generous, but it cannot leave the platform
without being wagered through. Without the cap, distribute() is a free
transfer rail that bypasses the whole rollover system.

Concurrency: every mutation locks the party row first, then user rows through
ledger.lock_user, same discipline as matches.
"""
import logging
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import (
    Party,
    PartyLog,
    PartyLogKind,
    PartyMember,
    SplitMode,
    TransactionType,
)
from app.services import ledger

logger = logging.getLogger("party")


class PartyError(Exception):
    pass


def max_party_size() -> int:
    # A party must fit on one side of some table, so the biggest allowed
    # format bounds it.
    return max(settings.allowed_team_sizes_list)


async def _lock_party(db: AsyncSession, party_id: int) -> Party:
    party = (
        await db.execute(
            select(Party).where(Party.id == party_id).with_for_update()
        )
    ).scalar_one_or_none()
    if party is None:
        raise PartyError("party not found")
    return party


async def members_of(db: AsyncSession, party_id: int) -> list[PartyMember]:
    rows = (
        await db.execute(
            select(PartyMember)
            .where(PartyMember.party_id == party_id)
            .order_by(PartyMember.id)
        )
    ).scalars().all()
    return list(rows)


async def membership(db: AsyncSession, user_id: int) -> PartyMember | None:
    return (
        await db.execute(
            select(PartyMember).where(PartyMember.user_id == user_id)
        )
    ).scalar_one_or_none()


async def create_party(db: AsyncSession, *, leader_id: int) -> Party:
    if await membership(db, leader_id) is not None:
        raise PartyError("you are already in a party")
    party = Party(
        leader_id=leader_id,
        split_mode=SplitMode.PROPORTIONAL,
        invite_code=uuid.uuid4().hex[:8],
    )
    db.add(party)
    await db.flush()
    db.add(PartyMember(party_id=party.id, user_id=leader_id))
    await db.commit()
    await db.refresh(party)
    return party


async def join_party(db: AsyncSession, *, user_id: int, invite_code: str) -> Party:
    party = (
        await db.execute(
            select(Party)
            .where(Party.invite_code == invite_code)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if party is None:
        raise PartyError("invite not found")
    if await membership(db, user_id) is not None:
        raise PartyError("you are already in a party")
    if len(await members_of(db, party.id)) >= max_party_size():
        raise PartyError("party is full")
    db.add(PartyMember(party_id=party.id, user_id=user_id))
    await db.commit()
    await db.refresh(party)
    return party


async def _reclaim_member(
    db: AsyncSession, party: Party, member: PartyMember
) -> None:
    """Return a member's entire entitlement to their personal balance."""
    if member.entitlement > 0:
        amount = member.entitlement
        user = await ledger.lock_user(db, member.user_id)
        await ledger.credit(
            db, user=user, tx_type=TransactionType.REFUND, amount=amount
        )
        party.pool_balance = ledger.quantize(party.pool_balance - amount)
        member.entitlement = Decimal("0.00")
        db.add(
            PartyLog(
                party_id=party.id,
                user_id=member.user_id,
                kind=PartyLogKind.RECLAIM,
                amount=amount,
            )
        )


async def leave_party(db: AsyncSession, *, user_id: int) -> None:
    """Leave, taking your entitlement with you. The leader leaving disbands.

    Disband returns every member's entitlement — pool money never gets
    stranded, and never moves to anyone but its proportional owner.
    """
    member = await membership(db, user_id)
    if member is None:
        raise PartyError("you are not in a party")
    party = await _lock_party(db, member.party_id)

    if party.leader_id == user_id:
        for m in await members_of(db, party.id):
            await _reclaim_member(db, party, m)
            await db.delete(m)
        await db.delete(party)
    else:
        await _reclaim_member(db, party, member)
        await db.delete(member)
    await db.commit()


async def kick_member(
    db: AsyncSession, *, leader_id: int, user_id: int
) -> Party:
    member = await membership(db, leader_id)
    if member is None:
        raise PartyError("you are not in a party")
    party = await _lock_party(db, member.party_id)
    if party.leader_id != leader_id:
        raise PartyError("only the leader can kick")
    if user_id == leader_id:
        raise PartyError("leaders leave by disbanding, not kicking themselves")
    target = await membership(db, user_id)
    if target is None or target.party_id != party.id:
        raise PartyError("that player is not in your party")
    await _reclaim_member(db, party, target)
    await db.delete(target)
    await db.commit()
    await db.refresh(party)
    return party


async def set_split_mode(
    db: AsyncSession, *, leader_id: int, mode: SplitMode
) -> Party:
    member = await membership(db, leader_id)
    if member is None:
        raise PartyError("you are not in a party")
    party = await _lock_party(db, member.party_id)
    if party.leader_id != leader_id:
        raise PartyError("only the leader can change the split mode")
    party.split_mode = mode
    await db.commit()
    await db.refresh(party)
    return party


async def contribute(
    db: AsyncSession, *, user_id: int, amount: Decimal
) -> Party:
    """Move personal balance into the pool. Raises the member's entitlement 1:1."""
    amount = ledger.quantize(amount)
    if amount <= 0:
        raise PartyError("contribution must be positive")
    member = await membership(db, user_id)
    if member is None:
        raise PartyError("you are not in a party")
    party = await _lock_party(db, member.party_id)

    user = await ledger.lock_user(db, user_id)
    await ledger.debit(
        db, user=user, tx_type=TransactionType.ESCROW, amount=amount
    )
    party.pool_balance = ledger.quantize(party.pool_balance + amount)
    member.entitlement = ledger.quantize(member.entitlement + amount)
    db.add(
        PartyLog(
            party_id=party.id,
            user_id=user_id,
            kind=PartyLogKind.CONTRIBUTE,
            amount=amount,
        )
    )
    await db.commit()
    await db.refresh(party)
    return party


async def reclaim(db: AsyncSession, *, user_id: int, amount: Decimal) -> Party:
    """Take your own share back out — capped at your entitlement, no questions."""
    amount = ledger.quantize(amount)
    if amount <= 0:
        raise PartyError("amount must be positive")
    member = await membership(db, user_id)
    if member is None:
        raise PartyError("you are not in a party")
    party = await _lock_party(db, member.party_id)
    if amount > member.entitlement:
        raise PartyError(
            f"your share of the pool is {member.entitlement}"
        )
    user = await ledger.lock_user(db, user_id)
    await ledger.credit(
        db, user=user, tx_type=TransactionType.REFUND, amount=amount
    )
    party.pool_balance = ledger.quantize(party.pool_balance - amount)
    member.entitlement = ledger.quantize(member.entitlement - amount)
    db.add(
        PartyLog(
            party_id=party.id,
            user_id=user_id,
            kind=PartyLogKind.RECLAIM,
            amount=amount,
        )
    )
    await db.commit()
    await db.refresh(party)
    return party


async def distribute(
    db: AsyncSession, *, leader_id: int, user_id: int, amount: Decimal
) -> Party:
    """Leader pays pool money out to a member — the constrained "Leader Decides".

    Up to the recipient's entitlement is theirs by right and moves freely.
    Anything above that is a GIFT out of the leader's own entitlement, and the
    gifted slice raises the recipient's rollover requirement by the same
    amount: a sponsored free-rider can be paid, but that money has to be
    wagered through before it can be withdrawn. This is what stops
    "Leader Decides" being a laundering rail between accounts.
    """
    amount = ledger.quantize(amount)
    if amount <= 0:
        raise PartyError("amount must be positive")
    leader_m = await membership(db, leader_id)
    if leader_m is None:
        raise PartyError("you are not in a party")
    party = await _lock_party(db, leader_m.party_id)
    if party.leader_id != leader_id:
        raise PartyError("only the leader can distribute the pool")

    target = await membership(db, user_id)
    if target is None or target.party_id != party.id:
        raise PartyError("that player is not in your party")

    own_share = min(target.entitlement, amount)
    gift = ledger.quantize(amount - own_share)
    if user_id == leader_id and gift > 0:
        raise PartyError(f"your share of the pool is {target.entitlement}")
    if gift > leader_m.entitlement:
        raise PartyError(
            f"you can top up at most {leader_m.entitlement} from your own share"
        )

    user = await ledger.lock_user(db, user_id)
    await ledger.credit(
        db, user=user, tx_type=TransactionType.WIN, amount=amount
    )
    if gift > 0:
        # The gifted slice left the leader's identity for the recipient's, so
        # it must be played through before it can leave the platform.
        ledger.raise_rollover(user, gift)
        leader_m.entitlement = ledger.quantize(leader_m.entitlement - gift)
    target.entitlement = ledger.quantize(target.entitlement - own_share)
    party.pool_balance = ledger.quantize(party.pool_balance - amount)
    db.add(
        PartyLog(
            party_id=party.id,
            user_id=user_id,
            kind=PartyLogKind.PAYOUT,
            amount=amount,
        )
    )
    await db.commit()
    await db.refresh(party)
    return party


def allocate(
    total: Decimal, weights: list[tuple[int, Decimal]]
) -> dict[int, Decimal]:
    """Split `total` across keyed weights, exact to the cent.

    Largest-remainder: floor each share to cents, then hand the leftover cents
    to the largest fractional remainders. Sum of the result == total, always —
    the same discipline as the match payout split.
    """
    weight_sum = sum(w for _, w in weights)
    if weight_sum <= 0:
        raise PartyError("nothing to allocate against")
    cents = int(total * 100)
    raw = [(key, cents * w / weight_sum) for key, w in weights]
    floored = {key: int(r) for key, r in raw}
    leftover = cents - sum(floored.values())
    by_remainder = sorted(raw, key=lambda kr: (kr[1] - int(kr[1])), reverse=True)
    for key, _ in by_remainder[:leftover]:
        floored[key] += 1
    return {key: Decimal(v) / 100 for key, v in floored.items()}
