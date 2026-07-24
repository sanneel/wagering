"""SpinCounter: browse, open, join, leave 1v1 bracket tournaments.

A SpinCounter is a Tournament that is still PENDING (filling its bracket). Once
the last seat fills it locks, the Wheel of Fortune spins, and the bracket plays
out — so browse, create, and the live bracket all live here.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import SpinStatus, Tournament, User
from app.schemas import (
    SpinConfigOut,
    TournamentCreateRequest,
    TournamentOut,
)
from app.security import get_active_user, get_current_user
from app.serializers import serialize_tournament, serialize_tournaments
from app.services import demo, ledger, tournament_service

router = APIRouter(prefix="/spincounter", tags=["spincounter"])


@router.get("/config", response_model=SpinConfigOut)
async def spin_config() -> SpinConfigOut:
    """Bracket sizes, entry bounds and jackpot shape — drives the UI. Public."""
    return SpinConfigOut(
        sizes=settings.spin_sizes_list,
        min_entry=settings.spin_min_entry,
        max_entry=settings.spin_max_entry,
        rounds_best_of=settings.spin_rounds_best_of,
        jackpot_rake_percent=settings.spin_jackpot_rake_percent,
        jackpot_max_multiplier=settings.spin_jackpot_max_multiplier,
    )


@router.get("", response_model=list[TournamentOut])
async def list_tournaments(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    size: int | None = Query(None, ge=2, le=64, description="Filter by bracket size"),
    limit: int = Query(50, ge=1, le=100),
) -> list[TournamentOut]:
    """Open SpinCounters still waiting on entrants, newest first."""
    q = select(Tournament).where(Tournament.status == SpinStatus.PENDING)
    if size is not None:
        q = q.where(Tournament.size == size)
    rows = (
        await db.execute(
            q.order_by(Tournament.created_at.desc(), Tournament.id.desc()).limit(limit)
        )
    ).scalars().all()
    return await serialize_tournaments(db, list(rows), me_id=current_user.id)


@router.post("", response_model=TournamentOut, status_code=201)
async def create_tournament(
    body: TournamentCreateRequest,
    current_user: User = Depends(get_active_user),
    db: AsyncSession = Depends(get_db),
) -> TournamentOut:
    """Open a SpinCounter and take the first bracket seat."""
    try:
        t = await tournament_service.open_tournament(
            db,
            creator_id=current_user.id,
            entry_fee=body.entry_fee,
            size=body.size,
        )
    except ledger.InsufficientFunds:
        raise HTTPException(status_code=402, detail="insufficient balance")
    except tournament_service.TournamentError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # In demo mode, bots fill the bracket, the wheel spins, games auto-play.
    demo.schedule_tournament_simulation(t.id)
    return await serialize_tournament(db, t, me_id=current_user.id)


@router.post("/{tournament_id}/join", response_model=TournamentOut)
async def join_tournament(
    tournament_id: int,
    current_user: User = Depends(get_active_user),
    db: AsyncSession = Depends(get_db),
) -> TournamentOut:
    """Take a bracket seat. Locks + spins the wheel when the last seat fills."""
    try:
        t = await tournament_service.join_tournament(
            db, tournament_id=tournament_id, user_id=current_user.id
        )
    except ledger.InsufficientFunds:
        raise HTTPException(status_code=402, detail="insufficient balance")
    except tournament_service.TournamentError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Demo: joining a standing bot bracket is what brings it to life. Schedule on
    # any pre-finish status — taking the last seat locks it immediately, and the
    # bracket still has to play out and settle.
    if t.status in (SpinStatus.PENDING, SpinStatus.LOCKED, SpinStatus.LIVE):
        demo.schedule_tournament_simulation(tournament_id)
    return await serialize_tournament(db, t, me_id=current_user.id)


@router.post("/{tournament_id}/leave", response_model=TournamentOut)
async def leave_tournament(
    tournament_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TournamentOut:
    """Give up a seat while the bracket is still filling and take the buy-in back."""
    try:
        t = await tournament_service.leave_tournament(
            db, tournament_id=tournament_id, user_id=current_user.id
        )
    except tournament_service.TournamentError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return await serialize_tournament(db, t, me_id=current_user.id)


@router.delete("/{tournament_id}/cancel", response_model=TournamentOut)
async def cancel_tournament(
    tournament_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TournamentOut:
    """Cancel a still-filling SpinCounter and refund every entry. Any entrant may."""
    t = (
        await db.execute(select(Tournament).where(Tournament.id == tournament_id))
    ).scalar_one_or_none()
    if t is None:
        raise HTTPException(status_code=404, detail="tournament not found")
    if not await tournament_service.is_entrant(
        db, tournament_id=tournament_id, user_id=current_user.id
    ):
        raise HTTPException(status_code=403, detail="not an entrant")
    try:
        t = await tournament_service.cancel_and_refund(db, tournament_id=tournament_id)
    except tournament_service.TournamentError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return await serialize_tournament(db, t, me_id=current_user.id)


@router.get("/{tournament_id}", response_model=TournamentOut)
async def get_tournament(
    tournament_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TournamentOut:
    t = (
        await db.execute(select(Tournament).where(Tournament.id == tournament_id))
    ).scalar_one_or_none()
    if t is None:
        raise HTTPException(status_code=404, detail="tournament not found")
    # A PENDING bracket is public so a prospective entrant can read it from a
    # share link before committing a buy-in; once it locks, entrants only.
    if t.status != SpinStatus.PENDING and not await tournament_service.is_entrant(
        db, tournament_id=tournament_id, user_id=current_user.id
    ):
        raise HTTPException(status_code=403, detail="not an entrant")
    return await serialize_tournament(db, t, me_id=current_user.id)
