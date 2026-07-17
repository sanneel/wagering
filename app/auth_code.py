"""One-time use auth code store for JWT handoff.

Redis-backed by Redis or in-memory fallback.
"""
import asyncio
import time
from typing import Optional

from app.config import settings
from app.redis_client import redis_client, RedisError

# In-memory fallback for demo/single-instance use.
# Maps code -> (expiry_timestamp, jwt_token)
_CODE_STORE: dict[str, tuple[float, str]] = {}
_STORE_LOCK = asyncio.Lock()
_CODE_STORE_TTL = 60  # seconds


async def _cleanup_expired() -> None:
    now = time.time()
    expired = [code for code, (expires, _) in _CODE_STORE.items() if expires < now]
    for code in expired:
        _CODE_STORE.pop(code, None)


async def store_auth_code(code: str, jwt_token: str, expires_in: int = _CODE_STORE_TTL) -> None:
    """Store a one-time use code mapping to a JWT token."""
    if settings.redis_enabled:
        try:
            # Use SET with EX to set the key with expiration.
            # We expect the code to be unique (from secrets.token_urlsafe).
            # If there is a collision (extremely unlikely), we overwrite.
            await redis_client.set(code, jwt_token, ex=expires_in)
            return
        except RedisError:
            # Fall back to in-memory store
            pass
    # Fallback: in-memory store
    async with _STORE_LOCK:
        await _cleanup_expired()
        expires_at = time.time() + expires_in
        _CODE_STORE[code] = (expires_at, jwt_token)


async def consume_auth_code(code: str) -> Optional[str]:
    """Atomically retrieve and delete the JWT for a one-time use code.
    Returns the JWT if the code is valid and not used before, else None.
    """
    if settings.redis_enabled:
        try:
            # Try to use GETDEL if available (Redis 6.2+), else GET then DELETE.
            if hasattr(redis_client, 'getdel'):
                jwt_token = await redis_client.getdel(code)
            else:
                jwt_token = await redis_client.get(code)
                if jwt_token is not None:
                    await redis_client.delete(code)
            if jwt_token is not None:
                return jwt_token
        except (RedisError, AttributeError):
            # Fall back to in-memory store
            pass
    # In-memory fallback
    async with _STORE_LOCK:
        await _cleanup_expired()
        entry = _CODE_STORE.pop(code, None)
        if entry is None:
            return None
        expires_at, jwt_token = entry
        if expires_at < time.time():
            return None
        return jwt_token