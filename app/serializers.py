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

from app.models import (
    Match,
    MatchParticipant,
    MatchStatus,
    Team,
    Tournament,
    TournamentEntry,
    TournamentGame,
    User,
)
from app.services import party_service, tournament_service
from app.schemas import (
    MatchOut,
    MyMatchOut,
    PlayerPublic,
    RecentMatchOut,
    SeatOut,
    TableOut,
    TournamentEntryOut,
    TournamentGameOut,
    TournamentOut,
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
        SeatOut(
            team=s.team,
            player=_player(users, s.user_id),
            contributed=s.contributed,
            party_split=s.party_split,
        )
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


# ─── SpinCounter serialization ──────────────────────────────────────────


async def _tournament_entries(
    db: AsyncSession, tournament_ids: list[int]
) -> dict[int, list[TournamentEntry]]:
    if not tournament_ids:
        return {}
    rows = (
        await db.execute(
            select(TournamentEntry)
            .where(TournamentEntry.tournament_id.in_(tournament_ids))
            .order_by(TournamentEntry.seed.nullslast(), TournamentEntry.id)
        )
    ).scalars().all()
    out: dict[int, list[TournamentEntry]] = {tid: [] for tid in tournament_ids}
    for r in rows:
        out[r.tournament_id].append(r)
    return out


async def _tournament_games(
    db: AsyncSession, tournament_ids: list[int]
) -> dict[int, list[TournamentGame]]:
    if not tournament_ids:
        return {}
    rows = (
        await db.execute(
            select(TournamentGame)
            .where(TournamentGame.tournament_id.in_(tournament_ids))
            .order_by(TournamentGame.round, TournamentGame.slot)
        )
    ).scalars().all()
    out: dict[int, list[TournamentGame]] = {tid: [] for tid in tournament_ids}
    for r in rows:
        out[r.tournament_id].append(r)
    return out


def _tournament_base(
    t: Tournament,
    entries: list[TournamentEntry],
    games: list[TournamentGame],
    users: dict[int, User],
    me_id: int | None,
) -> dict:
    entry_out = [
        TournamentEntryOut(
            player=_player(users, e.user_id),
            seed=e.seed,
            eliminated=e.eliminated,
            is_wheel_winner=(e.user_id == t.wheel_winner_id),
            is_champion=(e.user_id == t.champion_id),
        )
        for e in entries
        if users.get(e.user_id)
    ]
    game_out = [
        TournamentGameOut(
            id=g.id,
            round=g.round,
            slot=g.slot,
            player_a=_player(users, g.player_a_id),
            player_b=_player(users, g.player_b_id),
            winner_id=g.winner_id,
            score_a=g.score_a,
            score_b=g.score_b,
            status=g.status,
        )
        for g in games
    ]
    return dict(
        id=t.id,
        creator_id=t.creator_id,
        size=t.size,
        entry_fee=t.entry_fee,
        rounds_best_of=t.rounds_best_of,
        status=t.status,
        prize_pool=t.prize_pool,
        rake_amount=t.rake_amount,
        wheel_prize=t.wheel_prize,
        wheel_segment_index=t.wheel_segment_index,
        wheel_winner=_player(users, t.wheel_winner_id),
        champion=_player(users, t.champion_id),
        rounds_total=tournament_service._rounds_for(t.size),
        entries=entry_out,
        games=game_out,
        entrants=len(entries),
        open_seats=max(0, t.size - len(entries)),
        joined=any(e.user_id == me_id for e in entries) if me_id else False,
        creator=_player(users, t.creator_id),
        created_at=t.created_at,
        finished_at=t.finished_at,
    )


async def serialize_tournament(
    db: AsyncSession, t: Tournament, me_id: int | None = None
) -> TournamentOut:
    entries = (await _tournament_entries(db, [t.id]))[t.id]
    games = (await _tournament_games(db, [t.id]))[t.id]
    uids: set[int] = {e.user_id for e in entries}
    uids.add(t.creator_id)
    for g in games:
        uids.update({g.player_a_id, g.player_b_id})
    if t.wheel_winner_id:
        uids.add(t.wheel_winner_id)
    if t.champion_id:
        uids.add(t.champion_id)
    users = await _load_users(db, uids)
    return TournamentOut(**_tournament_base(t, entries, games, users, me_id))


async def serialize_tournaments(
    db: AsyncSession, tournaments: list[Tournament], me_id: int | None = None
) -> list[TournamentOut]:
    ids = [t.id for t in tournaments]
    entries_by = await _tournament_entries(db, ids)
    games_by = await _tournament_games(db, ids)
    uids: set[int] = set()
    for t in tournaments:
        uids.add(t.creator_id)
        uids.update(e.user_id for e in entries_by.get(t.id, []))
        for g in games_by.get(t.id, []):
            uids.update({g.player_a_id, g.player_b_id})
        if t.wheel_winner_id:
            uids.add(t.wheel_winner_id)
        if t.champion_id:
            uids.add(t.champion_id)
    users = await _load_users(db, uids)
    return [
        TournamentOut(
            **_tournament_base(
                t,
                entries_by.get(t.id, []),
                games_by.get(t.id, []),
                users,
                me_id,
            )
        )
        for t in tournaments
    ]


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
        if m.status == MatchStatus.FINISHED and m.winning_team is not None and mine:
            if my_team == m.winning_team:
                result = "W"
                # Same contribution-weighted split settle used — same weights,
                # same seat order — so history shows the exact cents credited,
                # not an even-split approximation that's wrong for parties.
                winning = [s for s in seats if s.team == m.winning_team]
                shares = party_service.allocate(
                    m.pot_amount - m.rake_amount,
                    [(s.user_id, s.contributed) for s in winning],
                )
                payout = shares[me_id]
            else:
                result = "L"
                # What THIS player funded — a sponsor lost more than one stake,
                # a pool-sponsored free-rider lost nothing of their own.
                payout = -mine.contributed

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
