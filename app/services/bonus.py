"""Retention bonuses: first-deposit welcome match and a daily reward.

Every grant is a BONUS ledger credit that also raises the player's rollover
requirement, so bonus money must be wagered through before it can be withdrawn.
That is what keeps a bonus's net cost below its face value (the wagering pays
rake) and what stops bonus-farming — see docs/PLATFORM_ECONOMICS.md.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import TransactionType, User
from app.services import ledger


async def _grant(db: AsyncSession, user: User, amount: Decimal, rollover: Decimal) -> Decimal:
    """Credit a BONUS and raise rollover by amount × multiplier. Caller commits."""
    amount = ledger.quantize(amount)
    if amount <= 0:
        return Decimal("0.00")
    await ledger.credit(db, user=user, tx_type=TransactionType.BONUS, amount=amount)
    ledger.raise_rollover(user, amount * rollover)
    return amount


async def grant_welcome(db: AsyncSession, user: User, deposit_amount: Decimal) -> Decimal:
    """One-time match on the player's first deposit. Returns the bonus granted.

    Assumes the user row is already locked by the caller (it is — the deposit
    credit locked it). No-op if disabled or already claimed.
    """
    if not settings.welcome_bonus_enabled or user.welcome_bonus_claimed:
        return Decimal("0.00")
    bonus = min(
        ledger.quantize(deposit_amount * settings.welcome_bonus_percent / Decimal("100")),
        settings.welcome_bonus_max,
    )
    granted = await _grant(db, user, bonus, settings.welcome_bonus_rollover)
    user.welcome_bonus_claimed = True
    return granted


def daily_status(user: User) -> tuple[bool, Decimal, datetime | None]:
    """(available, amount, next_available_at) for the daily reward."""
    if not settings.daily_bonus_enabled:
        return False, Decimal("0.00"), None
    amount = ledger.quantize(settings.daily_bonus_amount)
    last = user.last_daily_bonus_at
    if last is None:
        return True, amount, None
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    next_at = last + timedelta(hours=settings.daily_bonus_cooldown_hours)
    return datetime.now(timezone.utc) >= next_at, amount, next_at


async def grant_daily(db: AsyncSession, user: User) -> Decimal:
    """Grant the daily reward if it's available, else raise. Caller commits."""
    available, amount, _ = daily_status(user)
    if not settings.daily_bonus_enabled:
        raise ValueError("daily reward is disabled")
    if not available:
        raise ValueError("daily reward already claimed — come back later")
    granted = await _grant(db, user, amount, settings.daily_bonus_rollover)
    user.last_daily_bonus_at = datetime.now(timezone.utc)
    return granted
