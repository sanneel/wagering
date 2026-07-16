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


class TransactionType(str, enum.Enum):
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    ESCROW = "ESCROW"        # wager locked out of balance into a match
    WIN = "WIN"             # payout credited to the winner
    REFUND = "REFUND"       # escrow returned on cancel


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    faceit_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    faceit_username: Mapped[str] = mapped_column(String(128))
    faceit_elo: Mapped[int] = mapped_column(default=0)
    avatar: Mapped[str | None] = mapped_column(String(512), nullable=True)
    balance: Mapped[Decimal] = mapped_column(Money, default=Decimal("0.00"))
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="user", lazy="noload"
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
