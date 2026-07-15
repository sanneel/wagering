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
    PENDING = "PENDING"      # created, waiting for both stakes to be escrowed
    LOCKED = "LOCKED"        # both stakes escrowed, FACEIT match created
    LIVE = "LIVE"            # match reported as started by FACEIT
    FINISHED = "FINISHED"    # settled, winner paid
    CANCELLED = "CANCELLED"  # aborted/cancelled, both refunded


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
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    player1_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), index=True
    )
    # Nullable: an open match waits for any opponent to accept.
    player2_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id"), index=True, nullable=True
    )
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
    winner_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    player1: Mapped["User"] = relationship(foreign_keys=[player1_id], lazy="noload")
    player2: Mapped["User"] = relationship(foreign_keys=[player2_id], lazy="noload")


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
