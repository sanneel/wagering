"""Current-user profile, history, rewards, and responsible-gaming controls."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import Match, MatchParticipant, Tournament, TournamentEntry, User
from app.schemas import (
    DailyClaimResponse,
    MyMatchOut,
    MyTournamentOut,
    RewardsOut,
    SelfExcludeRequest,
    SetLimitRequest,
    UserOut,
)
from app.security import get_current_user
from app.serializers import serialize_my_matches, serialize_my_tournaments
from app.services import bonus, ledger

router = APIRouter(tags=["users"])


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(current_user)


@router.get("/me/rewards", response_model=RewardsOut)
async def rewards(current_user: User = Depends(get_current_user)) -> RewardsOut:
    available, amount, next_at = bonus.daily_status(current_user)
    return RewardsOut(
        daily_available=available,
        daily_amount=amount,
        daily_next_at=next_at,
        welcome_claimed=current_user.welcome_bonus_claimed,
    )


@router.post("/me/rewards/daily", response_model=DailyClaimResponse)
async def claim_daily(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DailyClaimResponse:
    user = await ledger.lock_user(db, current_user.id)
    try:
        granted = await bonus.grant_daily(db, user)
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    await db.commit()
    _, _, next_at = bonus.daily_status(user)
    return DailyClaimResponse(granted=granted, balance=user.balance, next_at=next_at)


@router.put("/me/limits", response_model=UserOut)
async def set_limits(
    body: SetLimitRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    """Set or clear a self-imposed daily deposit cap (a responsible-gaming tool)."""
    user = await ledger.lock_user(db, current_user.id)
    if body.daily_deposit_limit is None:
        user.daily_deposit_limit = None
    else:
        user.daily_deposit_limit = min(
            ledger.quantize(body.daily_deposit_limit), settings.max_daily_deposit_limit
        )
    await db.commit()
    await db.refresh(user)
    return UserOut.model_validate(user)


@router.post("/me/self-exclude", response_model=UserOut)
async def self_exclude(
    body: SelfExcludeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    """Lock the account out of deposits and wagering for a chosen period.

    Only ever extends the exclusion — it can't be shortened, which is the point
    of a responsible-gaming lock.
    """
    user = await ledger.lock_user(db, current_user.id)
    until = datetime.now(timezone.utc) + timedelta(days=body.days)
    current = user.self_excluded_until
    if current is not None and current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    user.self_excluded_until = max(until, current) if current else until
    await db.commit()
    await db.refresh(user)
    return UserOut.model_validate(user)


@router.get("/me/matches", response_model=list[MyMatchOut])
async def my_matches(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[MyMatchOut]:
    """The current user's match history, framed from their side (W/L, payout).

    Membership is a seat, so this joins through participants rather than
    checking a pair of player columns.
    """
    matches = (
        await db.execute(
            select(Match)
            .join(MatchParticipant, MatchParticipant.match_id == Match.id)
            .where(MatchParticipant.user_id == current_user.id)
            .order_by(Match.created_at.desc(), Match.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return await serialize_my_matches(db, list(matches), current_user.id)


@router.get("/me/spincounters", response_model=list[MyTournamentOut])
async def my_spincounters(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[MyTournamentOut]:
    """The current user's SpinCounter history, framed from their side.

    Membership is an entry, so this joins through tournament_entries the same way
    match history joins through participants.
    """
    tournaments = (
        await db.execute(
            select(Tournament)
            .join(TournamentEntry, TournamentEntry.tournament_id == Tournament.id)
            .where(TournamentEntry.user_id == current_user.id)
            .order_by(Tournament.created_at.desc(), Tournament.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return await serialize_my_tournaments(db, list(tournaments), current_user.id)
