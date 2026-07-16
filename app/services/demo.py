"""Demo mode: a bot opponent and match auto-simulation so the whole product is
clickable without real FACEIT/Payed integrations.

Enabled by DEMO_MODE. None of this runs when DEMO_MODE is false.
"""
import asyncio
import logging
import random
import uuid
from decimal import Decimal

from sqlalchemy import func, select

from app.config import settings
from app.database import SessionLocal
from app.models import Match, MatchParticipant, MatchStatus, Team, User
from app.services import ledger, match_service

logger = logging.getLogger("demo")

BOT_FACEIT_ID = "demo-bot"
BOT_BALANCE = Decimal("1000000.00")


async def get_or_create_bot(db, slot: int = 0) -> User:
    """A distinct bot per seat — a 5v5 needs nine of them, each its own user."""
    faceit_id = BOT_FACEIT_ID if slot == 0 else f"{BOT_FACEIT_ID}-{slot}"
    bot = (
        await db.execute(select(User).where(User.faceit_id == faceit_id))
    ).scalar_one_or_none()
    if bot is None:
        bot = User(
            faceit_id=faceit_id,
            faceit_username="1v1wager Bot" if slot == 0 else f"BOT_{BOT_NAMES[slot % len(BOT_NAMES)]}",
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


BOT_NAMES = [
    "s1mple", "ZywOo", "NiKo", "device", "sh1ro",
    "electronic", "ropz", "blameF", "Twistzz", "KRIMZ",
]


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


# Tables whose simulation is already running. Every join schedules one, so
# without this a table two players join would get two sims racing to fill it.
_running: set[int] = set()


def schedule_simulation(match_id: int, delay: float = 6.0) -> None:
    """Fire-and-forget the demo table lifecycle: bots fill the seats, then settle.

    Only tables a human is sitting at get this. Seeded bot tables are left alone
    so they stay open to browse and join.
    """
    if not settings.demo_mode or match_id in _running:
        return
    _running.add(match_id)
    asyncio.create_task(_simulate(match_id, delay))


# Stakes/formats for the standing tables, so the browse list has a spread.
_SEED_TABLES = [(1, "5.00"), (1, "25.00"), (2, "10.00"), (5, "10.00"), (5, "50.00")]


async def seed_open_tables() -> None:
    """Keep a handful of open bot tables around for the lobby to show.

    Without this the browse list is empty in demo mode — there is only ever one
    human, and the bots fill their own table within seconds of it opening. These
    sit PENDING until someone takes a seat.
    """
    if not settings.demo_mode:
        return
    try:
        async with SessionLocal() as db:
            existing = (
                await db.execute(
                    select(func.count())
                    .select_from(Match)
                    .where(Match.status == MatchStatus.PENDING)
                )
            ).scalar_one()
            if existing >= len(_SEED_TABLES):
                return
            missing = _SEED_TABLES[existing:]

        for i, (team_size, wager) in enumerate(missing):
            async with SessionLocal() as db:
                host = await get_or_create_bot(db, 20 + i)
                locked = await ledger.lock_user(db, host.id)
                if locked.balance < Decimal("1000.00"):
                    locked.balance = BOT_BALANCE
                    await db.commit()
                host_id = host.id
            async with SessionLocal() as db:
                m = await match_service.open_table(
                    db, creator_id=host_id, wager=Decimal(wager), team_size=team_size
                )
                mid = m.id
            # Part-fill the bigger formats so they don't all look brand new.
            if team_size >= 2:
                for slot in range(team_size - 1):
                    async with SessionLocal() as db:
                        mate = await get_or_create_bot(db, 30 + i * 5 + slot)
                        locked = await ledger.lock_user(db, mate.id)
                        if locked.balance < Decimal("1000.00"):
                            locked.balance = BOT_BALANCE
                            await db.commit()
                        mate_id = mate.id
                    async with SessionLocal() as db:
                        await match_service.join_table(
                            db, match_id=mid, user_id=mate_id, team=Team.A
                        )
        logger.info("seeded %d open demo tables", len(missing))
    except Exception:  # noqa: BLE001 — seeding must never block startup
        logger.exception("failed to seed demo tables")


async def _simulate(match_id: int, delay: float = 6.0) -> None:
    """PENDING -> (bots take every free seat) LOCKED -> FINISHED, paced for polling.

    Bots fill whatever seats a real player hasn't taken, so a 1v1 needs one and
    a 5v5 needs up to nine. If humans join first the bots simply take fewer.
    """
    try:
        # Long enough that the table is visibly waiting first — the lobby polls
        # every 3s, so it should show seats open before they start filling.
        await asyncio.sleep(delay)

        async with SessionLocal() as db:
            match = (
                await db.execute(select(Match).where(Match.id == match_id))
            ).scalar_one_or_none()
            if match is None:
                return
            team_size = match.team_size
            seats = (
                await db.execute(
                    select(MatchParticipant).where(
                        MatchParticipant.match_id == match_id
                    )
                )
            ).scalars().all()

        taken = {Team.A: 0, Team.B: 0}
        for s in seats:
            taken[s.team] += 1
        need = [
            (team, team_size - taken[team]) for team in (Team.A, Team.B)
        ]

        slot = 0
        for team, count in need:
            for _ in range(count):
                async with SessionLocal() as db:
                    bot = await get_or_create_bot(db, slot)
                    # Keep the bot solvent.
                    locked = await ledger.lock_user(db, bot.id)
                    if locked.balance < Decimal("1000.00"):
                        locked.balance = BOT_BALANCE
                        await db.commit()
                    bot_id = bot.id
                slot += 1
                async with SessionLocal() as db:
                    await match_service.join_table(
                        db, match_id=match_id, user_id=bot_id, team=team
                    )

        # Simulate the match being played.
        await asyncio.sleep(6)

        async with SessionLocal() as db:
            rows = (
                await db.execute(
                    select(MatchParticipant.user_id, MatchParticipant.team, User.faceit_id)
                    .join(User, User.id == MatchParticipant.user_id)
                    .where(MatchParticipant.match_id == match_id)
                    .order_by(MatchParticipant.id)
                )
            ).all()
            humans = [r for r in rows if not r.faceit_id.startswith(BOT_FACEIT_ID)]
            # The human's side wins 55% of the time in the demo.
            if humans and random.random() < 0.55:
                winning_team = humans[0].team
            else:
                winning_team = random.choice([Team.A, Team.B])
            winner = next(r for r in rows if r.team == winning_team)
            await match_service.settle_finished(
                db, match_id=match_id, winner_faceit_id=winner.faceit_id
            )
            logger.info(
                "demo table %s settled, team %s won", match_id, winning_team.value
            )
    except Exception:  # noqa: BLE001 — demo sim must never crash the server
        logger.exception("demo simulation failed for table %s", match_id)
    finally:
        _running.discard(match_id)
