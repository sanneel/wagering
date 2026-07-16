"""Current-user profile and match history."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Match, MatchParticipant, User
from app.schemas import MyMatchOut, UserOut
from app.security import get_current_user
from app.serializers import serialize_my_matches

router = APIRouter(tags=["users"])


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(current_user)


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
