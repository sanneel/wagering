"""Helpers that turn Match ORM rows into nested API responses.

Matches only store player *ids*; these load the referenced users and embed them
as `PlayerPublic` objects so the frontend gets usernames / elo / avatars.
"""
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Match, MatchStatus, User
from app.schemas import MatchOut, MyMatchOut, PlayerPublic, RecentMatchOut


async def _load_users(db: AsyncSession, ids: set[int]) -> dict[int, User]:
    ids = {i for i in ids if i is not None}
    if not ids:
        return {}
    rows = (
        await db.execute(select(User).where(User.id.in_(ids)))
    ).scalars().all()
    return {u.id: u for u in rows}


def _player(users: dict[int, User], uid: int | None) -> PlayerPublic | None:
    u = users.get(uid) if uid is not None else None
    return PlayerPublic.model_validate(u) if u else None


async def serialize_match(db: AsyncSession, match: Match) -> MatchOut:
    users = await _load_users(db, {match.player1_id, match.player2_id})
    return MatchOut(
        id=match.id,
        player1_id=match.player1_id,
        player2_id=match.player2_id,
        player1=_player(users, match.player1_id),
        player2=_player(users, match.player2_id),
        wager_amount=match.wager_amount,
        pot_amount=match.pot_amount,
        rake_amount=match.rake_amount,
        status=match.status,
        faceit_match_id=match.faceit_match_id,
        winner_id=match.winner_id,
        created_at=match.created_at,
        finished_at=match.finished_at,
    )


async def serialize_recent(
    db: AsyncSession, matches: list[Match]
) -> list[RecentMatchOut]:
    ids: set[int] = set()
    for m in matches:
        ids.update({m.player1_id, m.player2_id, m.winner_id})
    users = await _load_users(db, ids)

    out: list[RecentMatchOut] = []
    for m in matches:
        p1 = _player(users, m.player1_id)
        p2 = _player(users, m.player2_id)
        winner = users.get(m.winner_id) if m.winner_id else None
        out.append(
            RecentMatchOut(
                id=m.id,
                player1=p1,
                player2=p2,
                player1_username=p1.faceit_username if p1 else None,
                player2_username=p2.faceit_username if p2 else None,
                winner_username=winner.faceit_username if winner else None,
                wager_amount=m.wager_amount,
                pot_amount=m.pot_amount,
                created_at=m.created_at,
                finished_at=m.finished_at,
            )
        )
    return out


async def serialize_my_matches(
    db: AsyncSession, matches: list[Match], me_id: int
) -> list[MyMatchOut]:
    ids: set[int] = set()
    for m in matches:
        ids.update({m.player1_id, m.player2_id})
    users = await _load_users(db, ids)

    out: list[MyMatchOut] = []
    for m in matches:
        opp_id = m.player2_id if m.player1_id == me_id else m.player1_id
        opponent = _player(users, opp_id)

        result: str | None = None
        payout: Decimal | None = None
        if m.status == MatchStatus.FINISHED and m.winner_id is not None:
            if m.winner_id == me_id:
                result = "W"
                payout = m.pot_amount - m.rake_amount
            else:
                result = "L"
                payout = -m.wager_amount

        out.append(
            MyMatchOut(
                id=m.id,
                opponent=opponent,
                opponent_username=opponent.faceit_username if opponent else None,
                wager_amount=m.wager_amount,
                status=m.status,
                result=result,
                payout=payout,
                created_at=m.created_at,
                finished_at=m.finished_at,
            )
        )
    return out
