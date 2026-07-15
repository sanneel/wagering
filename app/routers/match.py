"""Match creation, acceptance, status, and the public recent-matches feed."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Match, MatchStatus, User
from app.schemas import MatchCreateRequest, MatchOut, RecentMatchOut
from app.security import get_current_user
from app.serializers import serialize_match, serialize_recent
from app.services import demo, ledger, match_service

router = APIRouter(prefix="/match", tags=["match"])

# Public feed lives under /matches (plural), no auth.
public_router = APIRouter(prefix="/matches", tags=["match"])


@public_router.get("/recent", response_model=list[RecentMatchOut])
async def recent_matches(
    db: AsyncSession = Depends(get_db),
) -> list[RecentMatchOut]:
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


@router.post("/create", response_model=MatchOut, status_code=201)
async def create_match(
    body: MatchCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MatchOut:
    try:
        match = await match_service.create_match(
            db,
            challenger_id=current_user.id,
            wager=body.wager_amount,
        )
    except ledger.InsufficientFunds:
        raise HTTPException(status_code=402, detail="insufficient balance")
    except match_service.MatchError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # In demo mode, a bot opponent accepts and the match auto-settles.
    demo.schedule_simulation(match.id)
    return await serialize_match(db, match)


@router.post("/{match_id}/accept", response_model=MatchOut)
async def accept_match(
    match_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MatchOut:
    """Accept an open challenge: escrow your stake and lock the match."""
    try:
        match = await match_service.accept_match(
            db, match_id=match_id, opponent_id=current_user.id
        )
    except ledger.InsufficientFunds:
        raise HTTPException(status_code=402, detail="insufficient balance")
    except match_service.MatchError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return await serialize_match(db, match)


@router.delete("/{match_id}/cancel", response_model=MatchOut)
async def cancel_match(
    match_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MatchOut:
    """Cancel a not-yet-finished match and refund escrow. Either participant may."""
    match = (
        await db.execute(select(Match).where(Match.id == match_id))
    ).scalar_one_or_none()
    if match is None:
        raise HTTPException(status_code=404, detail="match not found")
    if current_user.id not in (match.player1_id, match.player2_id):
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
    if current_user.id not in (match.player1_id, match.player2_id):
        raise HTTPException(status_code=403, detail="not a participant")
    return await serialize_match(db, match)
