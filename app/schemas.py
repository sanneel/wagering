"""Pydantic request/response schemas."""
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models import MatchStatus, PartyLogKind, SplitMode, Team, TransactionType


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
    # Deposited money still to be wagered through; withdrawals are blocked
    # while it's above zero.
    rollover_requirement: Decimal = Decimal("0.00")
    # Fee-free allowance: deposits not yet taken back out.
    principal: Decimal = Decimal("0.00")
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


# ─── Tables / matches ───────────────────────────────────────────────────
class TableCreateRequest(BaseModel):
    wager_amount: Decimal = Field(..., gt=0, description="Stake per player")
    team_size: int = Field(
        1, ge=1, le=5, description="Seats per side: 1 => 1v1, 2 => 2v2, 5 => 5v5"
    )


class TableJoinRequest(BaseModel):
    # Omitted, the server seats you on the emptier side.
    team: Team | None = None


class SeatOut(BaseModel):
    """One filled seat."""

    team: Team
    player: PlayerPublic
    # What this seat's player funded — payouts and refunds follow this, so the
    # UI can show real per-player amounts instead of assuming an even split.
    contributed: Decimal = Decimal("0.00")
    # Set for party seats; LEADER means this seat's winnings bank to the party
    # pool rather than paying out personally.
    party_split: SplitMode | None = None


class MatchOut(BaseModel):
    id: int
    creator_id: int
    team_size: int
    wager_amount: Decimal
    pot_amount: Decimal
    rake_amount: Decimal
    status: MatchStatus
    faceit_match_id: str | None = None
    winning_team: Team | None = None
    created_at: datetime
    finished_at: datetime | None = None

    seats: list[SeatOut] = []
    # Denormalised for the lobby/browse UI so it needn't count seats itself.
    seats_taken: int = 0
    seats_total: int = 0
    open_seats: int = 0


class TableOut(MatchOut):
    """An open table in the browse list, plus the viewer's relationship to it."""

    creator: PlayerPublic | None = None
    joined: bool = False


class FormatOut(BaseModel):
    """A format the server will accept, for building the UI's filters."""

    team_size: int
    label: str  # "1v1", "2v2", "5v5"


class RecentMatchOut(BaseModel):
    """Public landing-feed entry for a finished match."""

    id: int
    team_size: int
    team_a: list[PlayerPublic] = []
    team_b: list[PlayerPublic] = []
    winning_team: Team | None = None
    winner_username: str | None = None
    wager_amount: Decimal
    pot_amount: Decimal
    created_at: datetime
    finished_at: datetime | None = None


class MyMatchOut(BaseModel):
    """One row of the current user's match history, framed from their side."""

    id: int
    team_size: int
    team: Team | None = None
    teammates: list[PlayerPublic] = []
    opponents: list[PlayerPublic] = []
    opponent_username: str | None = None  # the side's name for 1v1, else "N players"
    wager_amount: Decimal
    status: MatchStatus
    result: str | None = None  # 'W' | 'L' | None (unfinished)
    payout: Decimal | None = None
    created_at: datetime
    finished_at: datetime | None = None


# ─── Party ──────────────────────────────────────────────────────────────
class PartyJoinRequest(BaseModel):
    invite_code: str = Field(..., min_length=4, max_length=16)


class PartySplitRequest(BaseModel):
    split_mode: SplitMode


class PartyAmountRequest(BaseModel):
    amount: Decimal = Field(..., gt=0)


class PartyDistributeRequest(BaseModel):
    user_id: int
    amount: Decimal = Field(..., gt=0)


class PartyMemberOut(BaseModel):
    player: PlayerPublic
    is_leader: bool
    # This member's claim on the pool — what they put in plus their share of
    # banked winnings. It is also the cap on what the leader may pay them.
    entitlement: Decimal


class PartyLogOut(BaseModel):
    """One Team Balance movement — the hover log."""

    username: str
    kind: PartyLogKind
    amount: Decimal
    match_id: int | None = None
    created_at: datetime


class PartyOut(BaseModel):
    id: int
    leader_id: int
    split_mode: SplitMode
    invite_code: str
    pool_balance: Decimal
    max_size: int
    members: list[PartyMemberOut] = []
    logs: list[PartyLogOut] = []
    # Formats this party fits into (team_size >= party size) — drives which
    # toggles the UI enables.
    allowed_team_sizes: list[int] = []


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
    amount: Decimal  # what actually lands, net of the fee
    fee: Decimal = Decimal("0.00")
    balance_after: Decimal


class WithdrawQuote(BaseModel):
    """What a withdrawal would cost, so the UI can show it before committing."""

    amount: Decimal
    own_funds: Decimal  # your own deposit coming back — never charged
    profit: Decimal  # the part above your deposits
    fee_percent: Decimal
    fee: Decimal
    you_receive: Decimal
    rollover_remaining: Decimal
    can_withdraw: bool
    reason: str | None = None


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
