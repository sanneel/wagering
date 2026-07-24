"""Deposits, withdrawals, and transaction history."""
import logging
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from app.config import settings
from app.database import get_db
from app.models import Transaction, TransactionType, User
from app.schemas import (
    DepositRequest,
    DepositResponse,
    TransactionOut,
    WithdrawQuote,
    WithdrawRequest,
    WithdrawResponse,
)
from app.security import get_current_user
from app.services import bonus, ledger, payed


async def _assert_can_deposit(db: AsyncSession, user: User, amount: Decimal) -> None:
    """Responsible-gaming gate on new deposits."""
    now = datetime.now(timezone.utc)
    excluded = user.self_excluded_until
    if excluded is not None:
        if excluded.tzinfo is None:
            excluded = excluded.replace(tzinfo=timezone.utc)
        if excluded > now:
            raise HTTPException(
                status_code=403,
                detail=f"self-excluded until {excluded.date().isoformat()}",
            )
    if user.daily_deposit_limit is not None:
        since = now - timedelta(hours=24)
        spent = (
            await db.execute(
                select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                    Transaction.user_id == user.id,
                    Transaction.type == TransactionType.DEPOSIT,
                    Transaction.created_at >= since,
                )
            )
        ).scalar_one()
        if ledger.quantize(Decimal(spent) + amount) > user.daily_deposit_limit:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"exceeds your ${user.daily_deposit_limit} daily deposit limit"
                ),
            )

logger = logging.getLogger("wallet")
router = APIRouter(prefix="/wallet", tags=["wallet"])


@router.post("/deposit", response_model=DepositResponse)
async def deposit(
    body: DepositRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DepositResponse:
    """Initiate a Payed.co hosted checkout.

    Funds are NOT credited here — the balance is credited only when Payed.co
    confirms the payment via /webhook/payed. We record a pending DEPOSIT ledger
    row keyed by payment_ref so the webhook can settle it idempotently.
    """
    amount = ledger.quantize(body.amount)
    if amount < settings.min_deposit:
        raise HTTPException(
            status_code=400, detail=f"minimum deposit is {settings.min_deposit}"
        )
    await _assert_can_deposit(db, current_user, amount)

    reference = f"dep-{current_user.id}-{uuid.uuid4().hex[:12]}"

    # Demo mode: credit the balance instantly, no payment provider.
    if settings.demo_mode:
        user = await ledger.lock_user(db, current_user.id)
        tx = await ledger.credit(
            db,
            user=user,
            tx_type=TransactionType.DEPOSIT,
            amount=amount,
            payment_ref=reference,
        )
        # A deposit raises the fee-free allowance (it's the user's own money)
        # and the amount that must be wagered through before it can leave.
        ledger.add_principal(user, amount)
        ledger.raise_rollover(user, amount * settings.rollover_multiplier)
        # First deposit earns the welcome bonus (BONUS credit + its own rollover).
        welcome = await bonus.grant_welcome(db, user, amount)
        await db.commit()
        await db.refresh(tx)
        return DepositResponse(
            transaction_id=tx.id,
            payment_ref=reference,
            checkout_url="",  # no redirect in demo; frontend refreshes balance
            amount=amount,
            bonus_granted=welcome,
        )

    try:
        result = await payed.create_deposit(
            amount=amount,
            currency="USD",
            reference=reference,
            user_faceit_id=current_user.faceit_id,
        )
    except payed.PayedError:
        logger.exception("deposit init failed for user %s", current_user.id)
        raise HTTPException(status_code=502, detail="payment provider error")

    # Record a pending (uncredited) deposit row; balance_after == current balance.
    tx = Transaction(
        user_id=current_user.id,
        type=TransactionType.DEPOSIT,
        amount=amount,
        balance_after=current_user.balance,
        payment_ref=result["payment_ref"],
    )
    db.add(tx)
    await db.commit()
    await db.refresh(tx)

    return DepositResponse(
        transaction_id=tx.id,
        payment_ref=result["payment_ref"],
        checkout_url=result["checkout_url"],
        amount=amount,
    )


@router.post("/withdraw", response_model=WithdrawResponse)
async def withdraw(
    body: WithdrawRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WithdrawResponse:
    """Debit the balance immediately, then request a Payed.co payout.

    The debit and ledger row are written inside one DB transaction with the user
    row locked. If the payout call fails, we refund atomically.
    """
    amount = ledger.quantize(body.amount)
    if amount < settings.min_withdrawal:
        raise HTTPException(
            status_code=400, detail=f"minimum withdrawal is {settings.min_withdrawal}"
        )
    if not current_user.is_verified:
        raise HTTPException(status_code=403, detail="account must be verified to withdraw")
    if current_user.rollover_requirement > 0:
        raise HTTPException(
            status_code=403,
            detail=(
                f"wager {current_user.rollover_requirement} more of your deposit "
                "before withdrawing"
            ),
        )

    reference = f"wd-{current_user.id}-{uuid.uuid4().hex[:12]}"

    async def _take(user: User) -> tuple[Transaction, Decimal, Decimal, Decimal]:
        """Debit the balance as a payout leg plus a fee leg.

        The balance always falls by the full `amount`; the user is paid
        `amount - fee`. Two rows rather than one so the ledger still sums to the
        balance and the house cut is its own auditable line.
        """
        own, profit = ledger.split_withdrawal(user, amount)
        fee = ledger.quantize(profit * settings.withdrawal_fee_fraction)
        payout_amount = ledger.quantize(amount - fee)
        tx = await ledger.debit(
            db,
            user=user,
            tx_type=TransactionType.WITHDRAWAL,
            amount=payout_amount,
            payment_ref=reference,
        )
        if fee > 0:
            await ledger.debit(
                db,
                user=user,
                tx_type=TransactionType.FEE,
                amount=fee,
                payment_ref=reference,
            )
        ledger.consume_principal(user, own)
        return tx, fee, payout_amount, own

    # Demo mode: debit instantly, no payout provider.
    if settings.demo_mode:
        user = await ledger.lock_user(db, current_user.id)
        if user.balance < amount:
            await db.rollback()
            raise HTTPException(status_code=402, detail="insufficient balance")
        tx, fee, payout_amount, _own = await _take(user)
        await db.commit()
        await db.refresh(tx)
        return WithdrawResponse(
            transaction_id=tx.id,
            payment_ref=reference,
            status="completed",
            amount=payout_amount,
            fee=fee,
            balance_after=user.balance,
        )

    # Lock + debit atomically.
    user = await ledger.lock_user(db, current_user.id)
    if user.balance < amount:
        await db.rollback()
        raise HTTPException(status_code=402, detail="insufficient balance")
    try:
        tx, fee, payout_amount, own = await _take(user)
        await db.commit()
        await db.refresh(tx)
    except ledger.InsufficientFunds:
        await db.rollback()
        raise HTTPException(status_code=402, detail="insufficient balance")

    # Request the payout for the net amount. On failure, reverse the whole
    # thing: the full `amount` back to the balance (fee leg included, since no
    # fee was earned) and the cost basis the withdrawal consumed.
    try:
        payout = await payed.create_payout(
            amount=payout_amount,
            currency="USD",
            reference=reference,
            destination=body.destination or "",
        )
    except payed.PayedError:
        logger.exception("payout failed for user %s; refunding", current_user.id)
        refund_user = await ledger.lock_user(db, current_user.id)
        await ledger.credit(
            db,
            user=refund_user,
            tx_type=TransactionType.REFUND,
            amount=amount,
            payment_ref=reference,
        )
        ledger.add_principal(refund_user, own)
        await db.commit()
        raise HTTPException(status_code=502, detail="payout failed; balance refunded")

    # Persist the provider payment_ref on the withdrawal row.
    tx.payment_ref = payout["payment_ref"]
    await db.commit()
    await db.refresh(tx)

    return WithdrawResponse(
        transaction_id=tx.id,
        payment_ref=payout["payment_ref"],
        status=payout["status"],
        amount=amount,
        balance_after=tx.balance_after,
    )


@router.get("/quote", response_model=WithdrawQuote)
async def withdraw_quote(
    amount: Decimal = Query(..., gt=0),
    current_user: User = Depends(get_current_user),
) -> WithdrawQuote:
    """Break a withdrawal down before it happens.

    The fee is a surprise worth spending a round trip to avoid — this shows
    which part is the user's own money coming back (free) and which part is
    profit (charged), plus why the button is disabled if it is.
    """
    amount = ledger.quantize(amount)
    own, profit = ledger.split_withdrawal(current_user, amount)
    fee = ledger.quantize(profit * settings.withdrawal_fee_fraction)

    reason: str | None = None
    if not current_user.is_verified:
        reason = "account must be verified to withdraw"
    elif current_user.rollover_requirement > 0:
        reason = (
            f"wager {current_user.rollover_requirement} more of your deposit first"
        )
    elif amount < settings.min_withdrawal:
        reason = f"minimum withdrawal is {settings.min_withdrawal}"
    elif current_user.balance < amount:
        reason = "insufficient balance"

    return WithdrawQuote(
        amount=amount,
        own_funds=own,
        profit=profit,
        fee_percent=settings.withdrawal_fee_percent,
        fee=fee,
        you_receive=ledger.quantize(amount - fee),
        rollover_remaining=current_user.rollover_requirement,
        can_withdraw=reason is None,
        reason=reason,
    )


@router.get("/transactions", response_model=list[TransactionOut])
async def transactions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[TransactionOut]:
    rows = (
        await db.execute(
            select(Transaction)
            .where(Transaction.user_id == current_user.id)
            .order_by(Transaction.created_at.desc(), Transaction.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return [TransactionOut.model_validate(r) for r in rows]
