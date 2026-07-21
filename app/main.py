"""1v1wager FastAPI application entrypoint."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import Base, engine
from app.middleware.geofencing import GeofencingMiddleware
from app.redis_client import redis_client
from app.routers import auth, match, party, users, wallet, webhook
from app.services import demo

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup must be fail-soft: on serverless every cold start runs this, and a
    # transient DB/Redis hiccup here would crash the whole function instead of
    # failing one request. Log and continue; handlers surface errors per-request.
    if settings.auto_create_tables:
        # For real production prefer Alembic migrations over create_all.
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        except Exception:  # noqa: BLE001
            logger.exception("startup create_all failed; continuing without it")
    if settings.redis_enabled:
        try:
            await redis_client.ping()
            logger.info("connected to redis")
        except Exception:  # noqa: BLE001
            logger.warning("redis unavailable at startup; state caching degraded")
    else:
        logger.info("redis disabled (redis_enabled=false)")
    # Demo mode has only one human, so without a few standing bot tables the
    # lobby's browse list would always be empty. Already guarded internally, but
    # keep it off the startup critical path so a DB blip can't take the app down.
    if settings.demo_mode:
        try:
            await demo.seed_open_tables()
        except Exception:  # noqa: BLE001
            logger.exception("demo seed failed; continuing")
    yield
    try:
        await redis_client.aclose()
    except Exception:  # noqa: BLE001
        pass
    await engine.dispose()


app = FastAPI(
    title="1v1wager API",
    description="P2P CS2 skill wagering platform",
    version="1.0.0",
    lifespan=lifespan,
)

dev_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
]
prod_origins = ["https://1v1wager.com"]

# Always allow the configured frontend origin (set FRONTEND_URL to your deployed
# Vercel domain) plus any extra origins from CORS_ORIGINS. Dev origins stay
# allowed outside production so local work keeps hitting a deployed API. With
# allow_credentials=True we can't use "*", so the set must be explicit.
allowed_origins = {settings.frontend_url, *prod_origins, *settings.cors_origins_list}
if settings.environment != "production":
    allowed_origins.update(dev_origins)

app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(o for o in allowed_origins if o),
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
app.include_router(party.router)
app.include_router(wallet.router)
app.include_router(webhook.router)


@app.get("/health", tags=["ops"])
async def health():
    return {"status": "ok", "app": settings.app_name, "env": settings.environment}
