"""Parties: create, invite, join, leave, and the pooled Team Balance."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import Party, PartyLog, User
from app.schemas import (
    PartyAmountRequest,
    PartyDistributeRequest,
    PartyJoinRequest,
    PartyLogOut,
    PartyMemberOut,
    PartyOut,
    PartySplitRequest,
    PlayerPublic,
)
from app.security import get_current_user
from app.services import ledger, party_service

router = APIRouter(prefix="/party", tags=["party"])


async def _serialize(db: AsyncSession, party: Party) -> PartyOut:
    members = await party_service.members_of(db, party.id)
    users = {
        u.id: u
        for u in (
            await db.execute(
                select(User).where(User.id.in_([m.user_id for m in members]))
            )
        ).scalars()
    }
    logs = (
        await db.execute(
            select(PartyLog)
            .where(PartyLog.party_id == party.id)
            .order_by(PartyLog.id.desc())
            .limit(30)
        )
    ).scalars().all()
    size = len(members)
    return PartyOut(
        id=party.id,
        leader_id=party.leader_id,
        split_mode=party.split_mode,
        invite_code=party.invite_code,
        pool_balance=party.pool_balance,
        max_size=party_service.max_party_size(),
        members=[
            PartyMemberOut(
                player=PlayerPublic.model_validate(users[m.user_id]),
                is_leader=m.user_id == party.leader_id,
                entitlement=m.entitlement,
            )
            for m in members
            if m.user_id in users
        ],
        logs=[
            PartyLogOut(
                username=users[l.user_id].faceit_username
                if l.user_id in users
                else "former member",
                kind=l.kind,
                amount=l.amount,
                match_id=l.match_id,
                created_at=l.created_at,
            )
            for l in logs
        ],
        allowed_team_sizes=[
            n for n in settings.allowed_team_sizes_list if n >= size
        ],
    )


async def _my_party(db: AsyncSession, user_id: int) -> Party | None:
    m = await party_service.membership(db, user_id)
    if m is None:
        return None
    return (
        await db.execute(select(Party).where(Party.id == m.party_id))
    ).scalar_one_or_none()


@router.get("", response_model=PartyOut | None)
async def my_party(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PartyOut | None:
    """The caller's party, or null — solo players simply have none."""
    party = await _my_party(db, current_user.id)
    return await _serialize(db, party) if party else None


@router.post("", response_model=PartyOut, status_code=201)
async def create_party(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PartyOut:
    try:
        party = await party_service.create_party(db, leader_id=current_user.id)
    except party_service.PartyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return await _serialize(db, party)


@router.post("/join", response_model=PartyOut)
async def join_party(
    body: PartyJoinRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PartyOut:
    try:
        party = await party_service.join_party(
            db, user_id=current_user.id, invite_code=body.invite_code.strip()
        )
    except party_service.PartyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return await _serialize(db, party)


@router.post("/leave", status_code=204)
async def leave_party(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Leave with your pool share. The leader leaving disbands the party."""
    try:
        await party_service.leave_party(db, user_id=current_user.id)
    except party_service.PartyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/kick/{user_id}", response_model=PartyOut)
async def kick(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PartyOut:
    try:
        party = await party_service.kick_member(
            db, leader_id=current_user.id, user_id=user_id
        )
    except party_service.PartyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return await _serialize(db, party)


@router.post("/split-mode", response_model=PartyOut)
async def set_split_mode(
    body: PartySplitRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PartyOut:
    """Leader-only. Visible to every member, and snapshotted onto each match at
    escrow — flipping it later never changes a match already queued."""
    try:
        party = await party_service.set_split_mode(
            db, leader_id=current_user.id, mode=body.split_mode
        )
    except party_service.PartyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return await _serialize(db, party)


@router.post("/contribute", response_model=PartyOut)
async def contribute(
    body: PartyAmountRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PartyOut:
    try:
        party = await party_service.contribute(
            db, user_id=current_user.id, amount=body.amount
        )
    except ledger.InsufficientFunds:
        raise HTTPException(status_code=402, detail="insufficient balance")
    except party_service.PartyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return await _serialize(db, party)


@router.post("/reclaim", response_model=PartyOut)
async def reclaim(
    body: PartyAmountRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PartyOut:
    try:
        party = await party_service.reclaim(
            db, user_id=current_user.id, amount=body.amount
        )
    except party_service.PartyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return await _serialize(db, party)


@router.post("/distribute", response_model=PartyOut)
async def distribute(
    body: PartyDistributeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PartyOut:
    """Leader pays pool money to a member — capped at their entitlement, with
    anything above it coming from the leader's own share and carrying a
    rollover requirement to the recipient."""
    try:
        party = await party_service.distribute(
            db,
            leader_id=current_user.id,
            user_id=body.user_id,
            amount=body.amount,
        )
    except party_service.PartyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return await _serialize(db, party)
