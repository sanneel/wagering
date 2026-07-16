"""1v1wager FastAPI application entrypoint."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import Base, engine
from app.middleware.geofencing import GeofencingMiddleware
from app.redis_client import redis_client
from app.routers import auth, match, users, wallet, webhook
from app.services import demo

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # In production use Alembic migrations instead of create_all.
    if settings.environment != "production":
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    if settings.redis_enabled:
        try:
            await redis_client.ping()
            logger.info("connected to redis")
        except Exception:  # noqa: BLE001
            logger.warning("redis unavailable at startup; state caching degraded")
    else:
        logger.info("redis disabled (redis_enabled=false)")
    # Demo mode has only one human, so without a few standing bot tables the
    # lobby's browse list would always be empty.
    await demo.seed_open_tables()
    yield
    await redis_client.aclose()
    await engine.dispose()


app = FastAPI(
    title="1v1wager API",
    description="P2P CS2 skill wagering platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://1v1wager.com"] if settings.environment == "production" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Geofencing runs on every non-exempt request.
app.add_middleware(GeofencingMiddleware)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(match.router)
app.include_router(match.public_router)
app.include_router(match.tables_router)
app.include_router(wallet.router)
app.include_router(webhook.router)


@app.get("/health", tags=["ops"])
async def health():
    return {"status": "ok", "app": settings.app_name, "env": settings.environment}
