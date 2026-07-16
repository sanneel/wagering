"""SQLAlchemy ORM models."""
import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# Money precision: 18 total digits, 2 decimal places.
Money = Numeric(18, 2)

# BIGINT on Postgres (BIGSERIAL identity), INTEGER on SQLite so its rowid
# autoincrement works — lets the app run on either without code changes.
BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class MatchStatus(str, enum.Enum):
    PENDING = "PENDING"      # open table, still filling seats
    LOCKED = "LOCKED"        # every seat taken and escrowed, FACEIT match created
    LIVE = "LIVE"            # match reported as started by FACEIT
    FINISHED = "FINISHED"    # settled, winning team paid
    CANCELLED = "CANCELLED"  # aborted/cancelled, everyone refunded


class Team(str, enum.Enum):
    """The two sides of a table. A is the creator's side."""

    A = "A"
    B = "B"


class SplitMode(str, enum.Enum):
    """How a party's winnings are divided.

    PROPORTIONAL pays each member straight to their personal balance by their
    funding share, at settle, automatically. LEADER banks the winnings in the
    party's pool instead; the leader then distributes — but capped, so it can't
    be used as a free transfer rail (see party_service.distribute).
    """

    PROPORTIONAL = "PROPORTIONAL"
    LEADER = "LEADER"


class PartyLogKind(str, enum.Enum):
    CONTRIBUTE = "CONTRIBUTE"  # member moved personal balance into the pool
    RECLAIM = "RECLAIM"        # member took their own share back out
    ESCROW = "ESCROW"          # pool funded a match seat
    REFUND = "REFUND"          # a cancelled match returned its escrow to the pool
    WIN = "WIN"                # match winnings banked into the pool (LEADER mode)
    PAYOUT = "PAYOUT"          # leader distributed pool money to a member


class TransactionType(str, enum.Enum):
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    ESCROW = "ESCROW"        # wager locked out of balance into a match
    WIN = "WIN"             # payout credited to the winning side
    REFUND = "REFUND"       # escrow returned on cancel
    FEE = "FEE"             # house cut, taken on the profit part of a withdrawal


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    faceit_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    faceit_username: Mapped[str] = mapped_column(String(128))
    faceit_elo: Mapped[int] = mapped_column(default=0)
    avatar: Mapped[str | None] = mapped_column(String(512), nullable=True)
    balance: Mapped[Decimal] = mapped_column(Money, default=Decimal("0.00"))

    # Cost basis: deposits made, less the deposited part already withdrawn. The
    # fee-free allowance on withdrawal — anything above it is profit and is
    # charged. Deliberately NOT reduced by losing a match: losing your deposit
    # doesn't mean the next withdrawal is profit.
    principal: Mapped[Decimal] = mapped_column(Money, default=Decimal("0.00"))

    # Deposited money still to be wagered through before any withdrawal is
    # allowed. Raised on deposit, burnt down when a match SETTLES.
    rollover_requirement: Mapped[Decimal] = mapped_column(Money, default=Decimal("0.00"))

    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="user", lazy="noload"
    )


class Party(Base):
    """A transient team: one leader, up to `max team size` members, one pool.

    The pool (Team Balance) is funded by members from their personal balances
    and is what pays the party's seats when it queues. `pool_balance` always
    equals the sum of the members' entitlements — an entitlement is a member's
    proportional claim on the pool, raised by their contributions and their
    share of banked winnings, drained when the pool escrows a match.
    """

    __tablename__ = "parties"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    leader_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), index=True
    )
    split_mode: Mapped[SplitMode] = mapped_column(
        SAEnum(SplitMode, name="split_mode"), default=SplitMode.PROPORTIONAL
    )
    invite_code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    pool_balance: Mapped[Decimal] = mapped_column(Money, default=Decimal("0.00"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    members: Mapped[list["PartyMember"]] = relationship(
        back_populates="party", lazy="noload", cascade="all, delete-orphan"
    )


class PartyMember(Base):
    """One member of a party. `user_id` is unique — you're in at most one party.

    `entitlement` is this member's claim on the party pool: what they've put in
    plus their proportional share of any winnings banked under LEADER mode. It
    is the cap on what the leader may pay them (their own money and their own
    share can always come back; more than that has to come out of the leader's
    entitlement, and inherits a rollover requirement — see distribute()).
    """

    __tablename__ = "party_members"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    party_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("parties.id"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), unique=True, index=True
    )
    entitlement: Mapped[Decimal] = mapped_column(Money, default=Decimal("0.00"))
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    party: Mapped["Party"] = relationship(back_populates="members", lazy="noload")
    user: Mapped["User"] = relationship(lazy="noload")


class PartyLog(Base):
    """Every pool movement, per member — the hover log behind Team Balance."""

    __tablename__ = "party_logs"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    party_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("parties.id"), index=True
    )
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    kind: Mapped[PartyLogKind] = mapped_column(
        SAEnum(PartyLogKind, name="party_log_kind")
    )
    amount: Mapped[Decimal] = mapped_column(Money)
    match_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("matches.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Match(Base):
    """A table: two sides of `team_size` seats each, every seat one escrowed stake.

    Seats live in `match_participants` rather than fixed player columns, so the
    same row serves 1v1, 2v2, 5v5 and anything else — `team_size` is just a
    number, and the allowed values are config (`ALLOWED_TEAM_SIZES`), not schema.
    """

    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    # Who opened the table. Always seated on team A.
    creator_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), index=True
    )
    # Seats per side: 1 => 1v1, 2 => 2v2, 5 => 5v5.
    team_size: Mapped[int] = mapped_column(Integer, default=1, index=True)
    # Stake per player, not the pot. Pot = wager * 2 * team_size.
    wager_amount: Mapped[Decimal] = mapped_column(Money)
    pot_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0.00"))
    rake_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0.00"))
    status: Mapped[MatchStatus] = mapped_column(
        SAEnum(MatchStatus, name="match_status"),
        default=MatchStatus.PENDING,
        index=True,
    )
    faceit_match_id: Mapped[str | None] = mapped_column(
        String(128), unique=True, index=True, nullable=True
    )
    winning_team: Mapped[Team | None] = mapped_column(
        SAEnum(Team, name="team"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    participants: Mapped[list["MatchParticipant"]] = relationship(
        back_populates="match", lazy="noload", cascade="all, delete-orphan"
    )


class MatchParticipant(Base):
    """One seat: a user on a side of a table, with their stake escrowed.

    A row here means the stake is already escrowed — seats are only written
    inside the same transaction as the ESCROW debit, so a seat can never exist
    without money behind it.
    """

    __tablename__ = "match_participants"
    __table_args__ = (
        # One seat per player per table.
        UniqueConstraint("match_id", "user_id", name="uq_participant_match_user"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    match_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("matches.id"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), index=True
    )
    team: Mapped[Team] = mapped_column(SAEnum(Team, name="team"))

    # What this player actually put into the pot. Solo seats fund their own
    # stake so it equals the table's stake; party seats are funded from the
    # pool, allocated by entitlement, so it can be anything from 0 (sponsored)
    # to several stakes (the sponsor). Drives both the payout split and how
    # much rollover this player burns when the match settles.
    contributed: Mapped[Decimal] = mapped_column(Money, default=Decimal("0.00"))

    # Snapshot of the party this seat queued with, taken at escrow. The split
    # mode is copied rather than read from the party at settle — otherwise a
    # leader could flip the toggle AFTER seeing the result, which is exactly
    # the bait-and-switch the visible toggle exists to prevent.
    party_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("parties.id"), nullable=True, index=True
    )
    party_split: Mapped[SplitMode | None] = mapped_column(
        SAEnum(SplitMode, name="split_mode"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    match: Mapped["Match"] = relationship(back_populates="participants", lazy="noload")
    user: Mapped["User"] = relationship(lazy="noload")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), index=True
    )
    type: Mapped[TransactionType] = mapped_column(
        SAEnum(TransactionType, name="transaction_type")
    )
    amount: Mapped[Decimal] = mapped_column(Money)
    balance_after: Mapped[Decimal] = mapped_column(Money)
    match_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("matches.id"), nullable=True, index=True
    )
    payment_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="transactions", lazy="noload")


Index("ix_transactions_user_created", Transaction.user_id, Transaction.created_at)
# Browsing open tables: filter by status + format, newest first.
Index("ix_matches_status_size", Match.status, Match.team_size, Match.created_at)
