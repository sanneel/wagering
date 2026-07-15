"""Deposits, withdrawals, and transaction history."""
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import Transaction, TransactionType, User
from app.schemas import (
    DepositRequest,
    DepositResponse,
    TransactionOut,
    WithdrawRequest,
    WithdrawResponse,
)
from app.security import get_current_user
from app.services import ledger, payed

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
        await db.commit()
        await db.refresh(tx)
        return DepositResponse(
            transaction_id=tx.id,
            payment_ref=reference,
            checkout_url="",  # no redirect in demo; frontend refreshes balance
            amount=amount,
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

    reference = f"wd-{current_user.id}-{uuid.uuid4().hex[:12]}"

    # Demo mode: debit instantly, no payout provider.
    if settings.demo_mode:
        user = await ledger.lock_user(db, current_user.id)
        if user.balance < amount:
            await db.rollback()
            raise HTTPException(status_code=402, detail="insufficient balance")
        tx = await ledger.debit(
            db,
            user=user,
            tx_type=TransactionType.WITHDRAWAL,
            amount=amount,
            payment_ref=reference,
        )
        await db.commit()
        await db.refresh(tx)
        return WithdrawResponse(
            transaction_id=tx.id,
            payment_ref=reference,
            status="completed",
            amount=amount,
            balance_after=tx.balance_after,
        )

    # Lock + debit atomically.
    user = await ledger.lock_user(db, current_user.id)
    if user.balance < amount:
        await db.rollback()
        raise HTTPException(status_code=402, detail="insufficient balance")
    try:
        tx = await ledger.debit(
            db,
            user=user,
            tx_type=TransactionType.WITHDRAWAL,
            amount=amount,
            payment_ref=reference,
        )
        await db.commit()
        await db.refresh(tx)
    except ledger.InsufficientFunds:
        await db.rollback()
        raise HTTPException(status_code=402, detail="insufficient balance")

    # Request the payout. On failure, refund the debit.
    try:
        payout = await payed.create_payout(
            amount=amount,
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
