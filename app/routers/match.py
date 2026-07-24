"""Tables: browse, open, join, leave — plus the public recent-matches feed.

A "table" is just a Match that is still PENDING (filling seats). Once every
seat is taken it locks and becomes a match, which is why both live here.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import Match, MatchStatus, User
from app.schemas import (
    FormatOut,
    MatchOut,
    RecentMatchOut,
    TableCreateRequest,
    TableJoinRequest,
    TableOut,
)
from app.security import get_active_user, get_current_user
from app.serializers import serialize_match, serialize_recent, serialize_tables
from app.services import demo, ledger, match_service

router = APIRouter(prefix="/match", tags=["match"])

# Tables + the public feed live under /matches and /tables (plural).
public_router = APIRouter(tags=["tables"])
tables_router = APIRouter(prefix="/tables", tags=["tables"])


@public_router.get("/matches/recent", response_model=list[RecentMatchOut])
async def recent_matches(db: AsyncSession = Depends(get_db)) -> list[RecentMatchOut]:
    """Last 10 finished matches — public, no auth."""
    matches = (
        await db.execute(
            select(Match)
            .where(Match.status == MatchStatus.FINISHED)
            .order_by(Match.finished_at.desc().nullslast(), Match.id.desc())
            .limit(10)
        )
    ).scalars().all()
    return await serialize_recent(db, list(matches))


@public_router.get("/formats", response_model=list[FormatOut])
async def formats() -> list[FormatOut]:
    """Formats this server accepts. Drives the UI's filters — public, no auth."""
    return [
        FormatOut(team_size=n, label=f"{n}v{n}")
        for n in settings.allowed_team_sizes_list
    ]


@tables_router.get("", response_model=list[TableOut])
async def list_tables(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    team_size: int | None = Query(None, ge=1, le=5, description="Filter by format"),
    limit: int = Query(50, ge=1, le=100),
) -> list[TableOut]:
    """Open tables still waiting on seats, newest first."""
    q = select(Match).where(Match.status == MatchStatus.PENDING)
    if team_size is not None:
        q = q.where(Match.team_size == team_size)
    matches = (
        await db.execute(q.order_by(Match.created_at.desc(), Match.id.desc()).limit(limit))
    ).scalars().all()
    return await serialize_tables(db, list(matches), me_id=current_user.id)


@tables_router.post("", response_model=MatchOut, status_code=201)
async def create_table(
    body: TableCreateRequest,
    current_user: User = Depends(get_active_user),
    db: AsyncSession = Depends(get_db),
) -> MatchOut:
    """Open a table and take the first seat."""
    try:
        match = await match_service.open_table(
            db,
            creator_id=current_user.id,
            wager=body.wager_amount,
            team_size=body.team_size,
        )
    except ledger.InsufficientFunds:
        raise HTTPException(status_code=402, detail="insufficient balance")
    except match_service.MatchError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # In demo mode, bots fill the remaining seats and the match auto-settles.
    demo.schedule_simulation(match.id)
    return await serialize_match(db, match)


@tables_router.post("/{match_id}/join", response_model=MatchOut)
async def join_table(
    match_id: int,
    body: TableJoinRequest | None = None,
    current_user: User = Depends(get_active_user),
    db: AsyncSession = Depends(get_db),
) -> MatchOut:
    """Take a seat. Locks the table once the last seat is filled."""
    try:
        match = await match_service.join_table(
            db,
            match_id=match_id,
            user_id=current_user.id,
            team=body.team if body else None,
        )
    except ledger.InsufficientFunds:
        raise HTTPException(status_code=402, detail="insufficient balance")
    except match_service.MatchError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Demo: joining a standing bot table is what brings it to life. Schedule on
    # any live status, not just PENDING — taking the last seat of a 1v1 locks it
    # immediately, and that table still has to play out and settle.
    if match.status in (MatchStatus.PENDING, MatchStatus.LOCKED):
        demo.schedule_simulation(match.id)
    return await serialize_match(db, match)


@tables_router.post("/{match_id}/leave", response_model=MatchOut)
async def leave_table(
    match_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MatchOut:
    """Give up a seat while the table is still filling, and take the stake back."""
    try:
        match = await match_service.leave_table(
            db, match_id=match_id, user_id=current_user.id
        )
    except match_service.MatchError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return await serialize_match(db, match)


@router.delete("/{match_id}/cancel", response_model=MatchOut)
async def cancel_match(
    match_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MatchOut:
    """Cancel a not-yet-finished table and refund every seat. Any participant may."""
    match = (
        await db.execute(select(Match).where(Match.id == match_id))
    ).scalar_one_or_none()
    if match is None:
        raise HTTPException(status_code=404, detail="match not found")
    if not await match_service.is_participant(
        db, match_id=match_id, user_id=current_user.id
    ):
        raise HTTPException(status_code=403, detail="not a participant")
    try:
        match = await match_service.cancel_and_refund(db, match_id=match_id)
    except match_service.MatchError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return await serialize_match(db, match)


@router.get("/{match_id}", response_model=MatchOut)
async def get_match(
    match_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MatchOut:
    match = (
        await db.execute(select(Match).where(Match.id == match_id))
    ).scalar_one_or_none()
    if match is None:
        raise HTTPException(status_code=404, detail="match not found")
    # Anyone seated can watch. An open table is public so a prospective joiner
    # can read it from its share link before committing a stake.
    if match.status != MatchStatus.PENDING and not await match_service.is_participant(
        db, match_id=match_id, user_id=current_user.id
    ):
        raise HTTPException(status_code=403, detail="not a participant")
    return await serialize_match(db, match)
