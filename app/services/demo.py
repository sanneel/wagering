"""Demo mode: a bot opponent and match auto-simulation so the whole product is
clickable without real FACEIT/Payed integrations.

Enabled by DEMO_MODE. None of this runs when DEMO_MODE is false.
"""
import asyncio
import logging
import random
import uuid
from decimal import Decimal

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import User
from app.services import ledger, match_service

logger = logging.getLogger("demo")

BOT_FACEIT_ID = "demo-bot"
BOT_BALANCE = Decimal("1000000.00")


async def get_or_create_bot(db) -> User:
    bot = (
        await db.execute(select(User).where(User.faceit_id == BOT_FACEIT_ID))
    ).scalar_one_or_none()
    if bot is None:
        bot = User(
            faceit_id=BOT_FACEIT_ID,
            faceit_username="1v1wager Bot",
            faceit_elo=random.randint(1400, 2200),
            avatar=None,
            balance=BOT_BALANCE,
            is_verified=True,
            is_demo=True,
        )
        db.add(bot)
        await db.commit()
        await db.refresh(bot)
    return bot


async def create_demo_user() -> User:
    """Create a fresh guest account with a starting balance."""
    async with SessionLocal() as db:
        suffix = uuid.uuid4().hex[:6]
        user = User(
            faceit_id=f"demo-{suffix}",
            faceit_username=f"guest-{suffix}",
            faceit_elo=random.randint(800, 2500),
            avatar=None,
            balance=settings.demo_start_balance,
            is_verified=True,
            is_demo=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


def schedule_simulation(match_id: int) -> None:
    """Fire-and-forget the demo match lifecycle for an open match."""
    if not settings.demo_mode:
        return
    asyncio.create_task(_simulate(match_id))


async def _simulate(match_id: int) -> None:
    """PENDING -> (bot accepts) LOCKED -> (settle) FINISHED, paced for polling."""
    try:
        # Give the human a moment to see "Waiting for opponent…".
        await asyncio.sleep(3)

        async with SessionLocal() as db:
            bot = await get_or_create_bot(db)
            # Keep the bot solvent.
            locked_bot = await ledger.lock_user(db, bot.id)
            if locked_bot.balance < Decimal("1000.00"):
                locked_bot.balance = BOT_BALANCE
                await db.commit()
            bot_id = bot.id

        async with SessionLocal() as db:
            match = await match_service.accept_match(
                db, match_id=match_id, opponent_id=bot_id
            )
            p1_id, p2_id = match.player1_id, match.player2_id

        # Simulate the match being played.
        await asyncio.sleep(6)

        async with SessionLocal() as db:
            users = (
                await db.execute(
                    select(User).where(User.id.in_([p1_id, p2_id]))
                )
            ).scalars().all()
            by_id = {u.id: u for u in users}
            # The human (player1) wins 55% of the time in the demo.
            winner_id = p1_id if random.random() < 0.55 else p2_id
            winner = by_id[winner_id]
            await match_service.settle_finished(
                db, match_id=match_id, winner_faceit_id=winner.faceit_id
            )
            logger.info("demo match %s settled, winner %s", match_id, winner_id)
    except Exception:  # noqa: BLE001 — demo sim must never crash the server
        logger.exception("demo simulation failed for match %s", match_id)
