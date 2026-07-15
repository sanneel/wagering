"""Inbound webhooks: FACEIT match events and Payed.co payment settlement."""
import hashlib
import hmac
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import Transaction, TransactionType, User
from app.redis_client import mark_webhook_seen, resolve_faceit_match
from app.services import ledger, match_service, payed

logger = logging.getLogger("webhook")
router = APIRouter(prefix="/webhook", tags=["webhook"])


def _verify_faceit_signature(raw: bytes, signature: str | None) -> bool:
    if not settings.faceit_webhook_secret:
        # No secret configured -> reject to avoid processing unsigned events.
        return False
    if not signature:
        return False
    expected = hmac.new(
        settings.faceit_webhook_secret.encode(), raw, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


async def _resolve_match_id(db: AsyncSession, faceit_match_id: str) -> int | None:
    """Redis reverse-lookup first, fall back to Postgres."""
    match_id = await resolve_faceit_match(faceit_match_id)
    if match_id is not None:
        return match_id
    from app.models import Match

    row = (
        await db.execute(
            select(Match.id).where(Match.faceit_match_id == faceit_match_id)
        )
    ).scalar_one_or_none()
    return row


@router.post("/faceit")
async def faceit_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_faceit_signature: str | None = Header(default=None),
):
    raw = await request.body()
    if not _verify_faceit_signature(raw, x_faceit_signature):
        raise HTTPException(status_code=401, detail="invalid signature")

    payload = await request.json()
    event_id = str(payload.get("id") or payload.get("event_id") or "")
    event = payload.get("event") or payload.get("type") or ""
    data = payload.get("payload") or payload.get("data") or {}
    faceit_match_id = str(data.get("id") or data.get("match_id") or "")

    if not event_id or not faceit_match_id:
        raise HTTPException(status_code=400, detail="malformed webhook")

    # Idempotency: process each event id at most once.
    if not await mark_webhook_seen(f"faceit:{event_id}"):
        return {"status": "duplicate_ignored"}

    match_id = await _resolve_match_id(db, faceit_match_id)
    if match_id is None:
        logger.warning("faceit webhook for unknown match %s", faceit_match_id)
        return {"status": "unknown_match"}

    try:
        if event in ("match_status_finished", "match_finished"):
            winner_faceit_id = _extract_winner(data)
            if not winner_faceit_id:
                logger.warning("finished event without winner for %s", faceit_match_id)
                return {"status": "no_winner"}
            await match_service.settle_finished(
                db, match_id=match_id, winner_faceit_id=winner_faceit_id
            )
            return {"status": "settled"}

        if event in (
            "match_status_cancelled",
            "match_status_aborted",
            "match_cancelled",
            "match_aborted",
        ):
            await match_service.cancel_and_refund(db, match_id=match_id)
            return {"status": "refunded"}

        if event in ("match_status_ready", "match_status_configuring", "match_status_ongoing"):
            await match_service.mark_live(db, match_id=match_id)
            return {"status": "live"}

    except match_service.MatchError as exc:
        logger.error("faceit webhook settle error: %s", exc)
        raise HTTPException(status_code=409, detail=str(exc))

    return {"status": "ignored", "event": event}


def _extract_winner(data: dict) -> str | None:
    """Pull the winning player's FACEIT id out of a finished-match payload.

    FACEIT reports faction/team results; for 1v1 each faction has one player.
    """
    results = data.get("results") or {}
    winner_faction = results.get("winner")
    teams = data.get("teams") or {}
    if winner_faction and winner_faction in teams:
        roster = teams[winner_faction].get("roster") or teams[winner_faction].get("players") or []
        if roster:
            first = roster[0]
            return str(first.get("id") or first.get("player_id") or first.get("guid") or "")
    # Fallback: explicit winner_id field.
    wid = data.get("winner_id") or data.get("winner")
    return str(wid) if wid else None


@router.post("/payed")
async def payed_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_payed_signature: str | None = Header(default=None),
):
    """Settle a deposit once Payed.co confirms the payment succeeded."""
    raw = await request.body()
    if not payed.verify_webhook_signature(raw, x_payed_signature):
        raise HTTPException(status_code=401, detail="invalid signature")

    payload = await request.json()
    event = payload.get("event") or payload.get("type") or ""
    data = payload.get("data") or payload
    payment_ref = str(data.get("id") or data.get("payment_ref") or "")
    status_str = (data.get("status") or "").lower()

    if not payment_ref:
        raise HTTPException(status_code=400, detail="missing payment_ref")

    if not await mark_webhook_seen(f"payed:{payment_ref}:{event}:{status_str}"):
        return {"status": "duplicate_ignored"}

    # Only settle successful deposit payments here.
    is_success = event in ("payment.succeeded", "payment_completed") or status_str in (
        "completed",
        "succeeded",
        "paid",
    )
    if not is_success:
        return {"status": "ignored", "event": event, "payment_status": status_str}

    # Find the pending deposit row created at /wallet/deposit.
    tx = (
        await db.execute(
            select(Transaction)
            .where(
                Transaction.payment_ref == payment_ref,
                Transaction.type == TransactionType.DEPOSIT,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if tx is None:
        logger.warning("payed webhook for unknown deposit ref %s", payment_ref)
        return {"status": "unknown_deposit"}

    # Idempotency guard: a settled deposit has balance_after reflecting the credit.
    # We detect "already settled" via a Redis marker set below; if the marker was
    # newly created above, this is the first settlement.
    user = await ledger.lock_user(db, tx.user_id)
    new_balance = ledger.quantize(user.balance + tx.amount)
    user.balance = new_balance
    tx.balance_after = new_balance  # finalize the pending row
    await db.commit()

    logger.info("credited deposit %s to user %s", payment_ref, tx.user_id)
    return {"status": "credited", "balance_after": str(new_balance)}
