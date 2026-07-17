"""Per-IP rate limiting as a FastAPI dependency.

Backed by Redis (see redis_client.rate_limit_ok) so a limit holds across every
app instance, not just one worker. Reuses the geofencing trusted-proxy logic for
client-IP resolution so a spoofed X-Forwarded-For can't be used to dodge a limit.
"""
from fastapi import Depends, HTTPException, Request

from app.middleware.geofencing import client_ip
from app.redis_client import rate_limit_ok


def rate_limit(*, limit: int, window_seconds: int, scope: str):
    """Build a dependency that allows `limit` requests per `window_seconds` per IP.

    `scope` namespaces the counter so different endpoints don't share a budget.
    """

    async def _dependency(request: Request) -> None:
        ip = client_ip(request) or "unknown"
        if not await rate_limit_ok(
            f"{scope}:{ip}", limit=limit, window_seconds=window_seconds
        ):
            raise HTTPException(
                status_code=429,
                detail="too many requests; slow down and try again shortly",
            )

    return Depends(_dependency)
