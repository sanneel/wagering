"""Pydantic request/response schemas."""
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models import MatchStatus, TransactionType


# ─── Auth ───────────────────────────────────────────────────────────────
class FaceitAuthRequest(BaseModel):
    code: str = Field(..., description="OAuth authorization code from FACEIT")
    redirect_uri: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: "UserOut"


# ─── User ───────────────────────────────────────────────────────────────
class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    faceit_id: str
    faceit_username: str
    faceit_elo: int
    avatar: str | None = None
    balance: Decimal
    is_verified: bool
    is_demo: bool = False
    created_at: datetime


class PlayerPublic(BaseModel):
    """Public-facing view of a player embedded in match responses."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    faceit_username: str
    faceit_elo: int
    avatar: str | None = None


# ─── Match ──────────────────────────────────────────────────────────────
class MatchCreateRequest(BaseModel):
    wager_amount: Decimal = Field(..., gt=0)


class MatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    player1_id: int
    player2_id: int | None
    player1: PlayerPublic | None = None
    player2: PlayerPublic | None = None
    wager_amount: Decimal
    pot_amount: Decimal
    rake_amount: Decimal
    status: MatchStatus
    faceit_match_id: str | None
    winner_id: int | None
    created_at: datetime
    finished_at: datetime | None


class RecentMatchOut(BaseModel):
    """Public landing-feed entry for a finished match."""

    id: int
    player1: PlayerPublic | None = None
    player2: PlayerPublic | None = None
    player1_username: str | None = None
    player2_username: str | None = None
    winner_username: str | None = None
    wager_amount: Decimal
    pot_amount: Decimal
    created_at: datetime
    finished_at: datetime | None = None


class MyMatchOut(BaseModel):
    """One row of the current user's match history, framed from their side."""

    id: int
    opponent: PlayerPublic | None = None
    opponent_username: str | None = None
    wager_amount: Decimal
    status: MatchStatus
    result: str | None = None  # 'W' | 'L' | None (unfinished)
    payout: Decimal | None = None
    created_at: datetime
    finished_at: datetime | None = None


# ─── Wallet ─────────────────────────────────────────────────────────────
class DepositRequest(BaseModel):
    amount: Decimal = Field(..., gt=0)


class DepositResponse(BaseModel):
    transaction_id: int
    payment_ref: str
    checkout_url: str
    amount: Decimal


class WithdrawRequest(BaseModel):
    amount: Decimal = Field(..., gt=0)
    # Optional for now — a real payout destination is collected later.
    destination: str | None = None


class WithdrawResponse(BaseModel):
    transaction_id: int
    payment_ref: str
    status: str
    amount: Decimal
    balance_after: Decimal


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: TransactionType
    amount: Decimal
    balance_after: Decimal
    match_id: int | None
    payment_ref: str | None
    created_at: datetime


TokenResponse.model_rebuild()
