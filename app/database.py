"""Async SQLAlchemy engine, session factory, and Base."""
import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import settings

# Vercel (and most FaaS platforms) set this on the running function.
_is_serverless = bool(os.getenv("VERCEL"))

# SQLite (used for the zero-dependency local demo) doesn't accept QueuePool
# sizing args; Postgres does. Configure accordingly.
_is_sqlite = settings.database_url.startswith("sqlite")
_engine_kwargs: dict = {"echo": settings.debug}
if _is_sqlite:
    # Wait (don't error) when the single writer is busy.
    _engine_kwargs["connect_args"] = {"timeout": 30}
elif _is_serverless:
    # Serverless functions scale horizontally and freeze between requests, so a
    # per-instance QueuePool would both exhaust Postgres connection limits and
    # hand out dead connections. Keep no pool of our own and connect through a
    # pooled endpoint (Neon "-pooler" host / Supabase :6543 / pgbouncer).
    # statement_cache_size=0 is required for pgbouncer transaction pooling;
    # ssl="require" satisfies managed Postgres (Neon/Supabase) which mandate TLS.
    _engine_kwargs.update(
        poolclass=NullPool,
        connect_args={"statement_cache_size": 0, "ssl": "require"},
    )
else:
    _engine_kwargs.update(
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
    )

engine = create_async_engine(settings.database_url, **_engine_kwargs)

if _is_sqlite:
    # WAL lets pollers read while the demo simulation writes the settle, so
    # matches finish promptly instead of queuing behind read locks.
    from sqlalchemy import event

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - demo only
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a session with automatic rollback on error."""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
