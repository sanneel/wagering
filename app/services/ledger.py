"""Money movement primitives.

Every balance mutation goes through this module so that:
  * the user row is locked (SELECT ... FOR UPDATE) before read-modify-write,
  * a Transaction ledger row is always written with the resulting balance,
  * callers compose these inside a single DB transaction (all-or-nothing).

These helpers DO NOT commit — the calling router/service owns the transaction
boundary so multiple operations settle atomically.
"""
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Transaction, TransactionType, User

CENTS = Decimal("0.01")


def quantize(amount: Decimal) -> Decimal:
    return amount.quantize(CENTS, rounding=ROUND_HALF_UP)


class InsufficientFunds(Exception):
    pass


async def lock_user(db: AsyncSession, user_id: int) -> User:
    """Fetch a user row with FOR UPDATE so concurrent balance ops serialize."""
    result = await db.execute(
        select(User).where(User.id == user_id).with_for_update()
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise ValueError(f"user {user_id} not found")
    return user


async def _apply(
    db: AsyncSession,
    *,
    user: User,
    tx_type: TransactionType,
    delta: Decimal,
    match_id: int | None = None,
    payment_ref: str | None = None,
) -> Transaction:
    """Apply a signed delta to a locked user and append a ledger row."""
    delta = quantize(delta)
    new_balance = quantize(user.balance + delta)
    if new_balance < Decimal("0.00"):
        raise InsufficientFunds(
            f"user {user.id} balance {user.balance} cannot absorb {delta}"
        )
    user.balance = new_balance
    tx = Transaction(
        user_id=user.id,
        type=tx_type,
        amount=quantize(abs(delta)),
        balance_after=new_balance,
        match_id=match_id,
        payment_ref=payment_ref,
    )
    db.add(tx)
    await db.flush()
    return tx


async def credit(
    db: AsyncSession,
    *,
    user: User,
    tx_type: TransactionType,
    amount: Decimal,
    match_id: int | None = None,
    payment_ref: str | None = None,
) -> Transaction:
    return await _apply(
        db,
        user=user,
        tx_type=tx_type,
        delta=abs(quantize(amount)),
        match_id=match_id,
        payment_ref=payment_ref,
    )


async def debit(
    db: AsyncSession,
    *,
    user: User,
    tx_type: TransactionType,
    amount: Decimal,
    match_id: int | None = None,
    payment_ref: str | None = None,
) -> Transaction:
    amount = quantize(amount)
    if user.balance < amount:
        raise InsufficientFunds(
            f"user {user.id} has {user.balance}, needs {amount}"
        )
    return await _apply(
        db,
        user=user,
        tx_type=tx_type,
        delta=-amount,
        match_id=match_id,
        payment_ref=payment_ref,
    )


# ─── Rollover / principal ───────────────────────────────────────────────
# Both counters live beside the balance and only move through these helpers.
# Callers must hold the user row (lock_user) first, same as any balance op.


def raise_rollover(user: User, amount: Decimal) -> None:
    """A deposit has to be wagered through before it can leave."""
    user.rollover_requirement = quantize(
        user.rollover_requirement + abs(quantize(amount))
    )


def burn_rollover(user: User, amount: Decimal) -> Decimal:
    """Retire wagered-through money. Clamped at zero; returns what was burnt.

    Only called when a match settles. Doing it at escrow would let a player open
    a table, cancel it for a full refund, and clear the requirement having
    wagered nothing.
    """
    amount = abs(quantize(amount))
    burnt = min(user.rollover_requirement, amount)
    user.rollover_requirement = quantize(user.rollover_requirement - burnt)
    return burnt


def add_principal(user: User, amount: Decimal) -> None:
    """A deposit raises the fee-free allowance by what was put in."""
    user.principal = quantize(user.principal + abs(quantize(amount)))


def split_withdrawal(user: User, amount: Decimal) -> tuple[Decimal, Decimal]:
    """Split a withdrawal into (own money back, profit) against the cost basis.

    The first slice is the user's own deposited money and is never charged; only
    what exceeds it is profit. Losing a match does not touch `principal`, so a
    player who deposits 100, loses 50 and withdraws 50 pays nothing — that 50 is
    still their own money coming home.
    """
    amount = quantize(amount)
    own = min(user.principal, amount)
    profit = quantize(amount - own)
    return own, profit


def consume_principal(user: User, own: Decimal) -> None:
    user.principal = quantize(user.principal - abs(quantize(own)))
