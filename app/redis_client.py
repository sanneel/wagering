"""Shared async Redis client used for match state and webhook idempotency."""
import logging

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import settings

logger = logging.getLogger("redis")

redis_client: Redis = Redis.from_url(
    settings.redis_url,
    encoding="utf-8",
    decode_responses=True,
    # Fail fast rather than hanging request handlers if Redis is unreachable.
    socket_connect_timeout=2,
    retry_on_timeout=False,
)


# ─── Match state helpers ────────────────────────────────────────────────
# Redis holds volatile, fast-read match state (independent of Postgres, which
# remains the source of truth for money). Keys:
#   match:state:{match_id}          -> hash of live fields
#   faceit:match:{faceit_match_id}  -> match_id  (reverse lookup for webhooks)
#   webhook:seen:{event_id}         -> idempotency marker (TTL)

MATCH_STATE_TTL = 60 * 60 * 24  # 24h
WEBHOOK_DEDUPE_TTL = 60 * 60 * 24 * 7  # 7d


async def set_match_state(match_id: int, fields: dict[str, str]) -> None:
    # Best-effort cache: Postgres is the source of truth, so a Redis outage
    # must never break match/money operations.
    if not settings.redis_enabled or not fields:
        return
    try:
        key = f"match:state:{match_id}"
        await redis_client.hset(key, mapping=fields)
        await redis_client.expire(key, MATCH_STATE_TTL)
    except RedisError as exc:
        logger.warning("redis set_match_state failed for %s: %s", match_id, exc)


async def get_match_state(match_id: int) -> dict[str, str]:
    if not settings.redis_enabled:
        return {}
    try:
        return await redis_client.hgetall(f"match:state:{match_id}")
    except RedisError as exc:
        logger.warning("redis get_match_state failed for %s: %s", match_id, exc)
        return {}


async def link_faceit_match(faceit_match_id: str, match_id: int) -> None:
    if not settings.redis_enabled:
        return
    try:
        await redis_client.set(
            f"faceit:match:{faceit_match_id}", str(match_id), ex=MATCH_STATE_TTL
        )
    except RedisError as exc:
        logger.warning("redis link_faceit_match failed for %s: %s", faceit_match_id, exc)


async def resolve_faceit_match(faceit_match_id: str) -> int | None:
    # On a Redis miss/outage the webhook handler falls back to a Postgres lookup.
    if not settings.redis_enabled:
        return None
    try:
        val = await redis_client.get(f"faceit:match:{faceit_match_id}")
        return int(val) if val else None
    except RedisError as exc:
        logger.warning("redis resolve_faceit_match failed for %s: %s", faceit_match_id, exc)
        return None


async def mark_webhook_seen(event_id: str) -> bool:
    """Return True if this is the first time we've seen event_id (i.e. process it)."""
    if not settings.redis_enabled:
        # No idempotency store available — process the event (demo/local only).
        return True
    # NX set returns True only if the key did not exist.
    created = await redis_client.set(
        f"webhook:seen:{event_id}", "1", nx=True, ex=WEBHOOK_DEDUPE_TTL
    )
    return bool(created)


# ─── Rate limiting ──────────────────────────────────────────────────────
async def rate_limit_ok(key: str, *, limit: int, window_seconds: int) -> bool:
    """Fixed-window per-key limiter shared across all app instances via Redis.

    Returns True while the caller is under `limit` requests in the current
    window. Fail-open: when Redis is disabled or unreachable we allow the
    request rather than lock everyone out (matches the rest of this module —
    Redis is a best-effort layer, never a hard dependency for demo/local).
    """
    if not settings.redis_enabled:
        return True
    try:
        full_key = f"ratelimit:{key}"
        count = await redis_client.incr(full_key)
        if count == 1:
            # First hit in this window — start the countdown.
            await redis_client.expire(full_key, window_seconds)
        return count <= limit
    except RedisError as exc:
        logger.warning("redis rate_limit failed for %s: %s", key, exc)
        return True
