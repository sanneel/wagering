"""Helpers that turn Match rows into nested API responses.

Seats live in `match_participants`, so these load a table's participants (and
the users behind them) and shape them per view: full rosters for the lobby,
two sides for the public feed, us-vs-them for a player's own history.

Each function batches its lookups — one query for the seats of every match it
was handed, one for the users those seats reference — so serialising a list of
tables stays two queries regardless of how many tables or seats are involved.
"""
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Match, MatchParticipant, MatchStatus, Team, User
from app.schemas import (
    MatchOut,
    MyMatchOut,
    PlayerPublic,
    RecentMatchOut,
    SeatOut,
    TableOut,
)


async def _seats_by_match(
    db: AsyncSession, match_ids: list[int]
) -> dict[int, list[MatchParticipant]]:
    if not match_ids:
        return {}
    rows = (
        await db.execute(
            select(MatchParticipant)
            .where(MatchParticipant.match_id.in_(match_ids))
            .order_by(MatchParticipant.id)
        )
    ).scalars().all()
    out: dict[int, list[MatchParticipant]] = {mid: [] for mid in match_ids}
    for r in rows:
        out[r.match_id].append(r)
    return out


async def _load_users(db: AsyncSession, ids: set[int]) -> dict[int, User]:
    ids = {i for i in ids if i is not None}
    if not ids:
        return {}
    rows = (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all()
    return {u.id: u for u in rows}


def _player(users: dict[int, User], uid: int | None) -> PlayerPublic | None:
    u = users.get(uid) if uid is not None else None
    return PlayerPublic.model_validate(u) if u else None


def _base(
    m: Match, seats: list[MatchParticipant], users: dict[int, User]
) -> dict:
    seat_out = [
        SeatOut(team=s.team, player=_player(users, s.user_id))
        for s in seats
        if users.get(s.user_id)
    ]
    total = m.team_size * 2
    return dict(
        id=m.id,
        creator_id=m.creator_id,
        team_size=m.team_size,
        wager_amount=m.wager_amount,
        pot_amount=m.pot_amount,
        rake_amount=m.rake_amount,
        status=m.status,
        faceit_match_id=m.faceit_match_id,
        winning_team=m.winning_team,
        created_at=m.created_at,
        finished_at=m.finished_at,
        seats=seat_out,
        seats_taken=len(seats),
        seats_total=total,
        open_seats=max(0, total - len(seats)),
    )


async def serialize_match(db: AsyncSession, match: Match) -> MatchOut:
    seats = (await _seats_by_match(db, [match.id]))[match.id]
    users = await _load_users(db, {s.user_id for s in seats})
    return MatchOut(**_base(match, seats, users))


async def serialize_tables(
    db: AsyncSession, matches: list[Match], me_id: int | None = None
) -> list[TableOut]:
    ids = [m.id for m in matches]
    seats_by = await _seats_by_match(db, ids)
    uids = {s.user_id for seats in seats_by.values() for s in seats}
    uids.update(m.creator_id for m in matches)
    users = await _load_users(db, uids)

    out: list[TableOut] = []
    for m in matches:
        seats = seats_by.get(m.id, [])
        out.append(
            TableOut(
                **_base(m, seats, users),
                creator=_player(users, m.creator_id),
                joined=any(s.user_id == me_id for s in seats) if me_id else False,
            )
        )
    return out


async def serialize_recent(
    db: AsyncSession, matches: list[Match]
) -> list[RecentMatchOut]:
    ids = [m.id for m in matches]
    seats_by = await _seats_by_match(db, ids)
    users = await _load_users(
        db, {s.user_id for seats in seats_by.values() for s in seats}
    )

    out: list[RecentMatchOut] = []
    for m in matches:
        seats = seats_by.get(m.id, [])
        a = [p for s in seats if s.team == Team.A and (p := _player(users, s.user_id))]
        b = [p for s in seats if s.team == Team.B and (p := _player(users, s.user_id))]
        won = a if m.winning_team == Team.A else b if m.winning_team == Team.B else []
        # 1v1 reads as a name; team games read as the side that took it.
        winner_username = (
            won[0].faceit_username
            if len(won) == 1
            else (f"Team {m.winning_team.value}" if m.winning_team else None)
        )
        out.append(
            RecentMatchOut(
                id=m.id,
                team_size=m.team_size,
                team_a=a,
                team_b=b,
                winning_team=m.winning_team,
                winner_username=winner_username,
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
    ids = [m.id for m in matches]
    seats_by = await _seats_by_match(db, ids)
    users = await _load_users(
        db, {s.user_id for seats in seats_by.values() for s in seats}
    )

    out: list[MyMatchOut] = []
    for m in matches:
        seats = seats_by.get(m.id, [])
        mine = next((s for s in seats if s.user_id == me_id), None)
        my_team = mine.team if mine else None

        teammates = [
            p
            for s in seats
            if s.team == my_team and s.user_id != me_id and (p := _player(users, s.user_id))
        ]
        opponents = [
            p
            for s in seats
            if my_team and s.team != my_team and (p := _player(users, s.user_id))
        ]

        result: str | None = None
        payout: Decimal | None = None
        if m.status == MatchStatus.FINISHED and m.winning_team is not None:
            if my_team == m.winning_team:
                result = "W"
                payout = (m.pot_amount - m.rake_amount) / m.team_size
            else:
                result = "L"
                payout = -m.wager_amount

        out.append(
            MyMatchOut(
                id=m.id,
                team_size=m.team_size,
                team=my_team,
                teammates=teammates,
                opponents=opponents,
                opponent_username=(
                    opponents[0].faceit_username
                    if len(opponents) == 1
                    else (f"{len(opponents)} players" if opponents else None)
                ),
                wager_amount=m.wager_amount,
                status=m.status,
                result=result,
                payout=payout,
                created_at=m.created_at,
                finished_at=m.finished_at,
            )
        )
    return out
