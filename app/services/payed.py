"""Thin async client around the Payed.co payment gateway.

Payed.co specifics (exact field names, signing scheme) vary by account; the
integration is isolated here so the rest of the app depends only on the two
operations we need: create a hosted deposit checkout, and initiate a payout.
"""
import hashlib
import hmac
import logging
from decimal import Decimal

import httpx

from app.config import settings

logger = logging.getLogger("payed")

_TIMEOUT = httpx.Timeout(15.0)


class PayedError(Exception):
    pass


def _auth_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.payed_api_key}",
        "Content-Type": "application/json",
    }


async def create_deposit(
    *, amount: Decimal, currency: str, reference: str, user_faceit_id: str
) -> dict:
    """Create a hosted checkout session. Returns {payment_ref, checkout_url}."""
    payload = {
        "amount": str(amount),
        "currency": currency,
        "reference": reference,
        "customer": {"external_id": user_faceit_id},
        "return_url": settings.deposit_return_url,
        "webhook_url": f"{settings.api_base_url}/webhook/payed",
    }
    url = f"{settings.payed_api_base}/payments"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(url, headers=_auth_headers(), json=payload)
    if resp.status_code not in (200, 201):
        logger.error("Payed deposit failed: %s %s", resp.status_code, resp.text)
        raise PayedError("Payed deposit creation failed")
    body = resp.json()
    payment_ref = body.get("id") or body.get("payment_ref")
    checkout_url = body.get("checkout_url") or body.get("url")
    if not payment_ref or not checkout_url:
        raise PayedError("Payed deposit response missing fields")
    return {"payment_ref": str(payment_ref), "checkout_url": checkout_url}


async def create_payout(
    *, amount: Decimal, currency: str, reference: str, destination: str
) -> dict:
    """Initiate a payout/withdrawal. Returns {payment_ref, status}."""
    payload = {
        "amount": str(amount),
        "currency": currency,
        "reference": reference,
        "destination": destination,
        "webhook_url": f"{settings.api_base_url}/webhook/payed",
    }
    url = f"{settings.payed_api_base}/payouts"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(url, headers=_auth_headers(), json=payload)
    if resp.status_code not in (200, 201):
        logger.error("Payed payout failed: %s %s", resp.status_code, resp.text)
        raise PayedError("Payed payout creation failed")
    body = resp.json()
    payment_ref = body.get("id") or body.get("payment_ref")
    if not payment_ref:
        raise PayedError("Payed payout response missing id")
    return {"payment_ref": str(payment_ref), "status": body.get("status", "pending")}


def verify_webhook_signature(raw_body: bytes, signature: str | None) -> bool:
    """Verify an inbound Payed.co webhook HMAC-SHA256 signature."""
    if not signature or not settings.payed_webhook_secret:
        return False
    expected = hmac.new(
        settings.payed_webhook_secret.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
