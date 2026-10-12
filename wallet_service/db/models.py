from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from wallet_service.db.session import Base


class DepositStatus(str, Enum):
    PENDING = "pending"
    PAID = "paid"
    PARTIALLY_PAID = "partially_paid"
    EXPIRED = "expired"


FINAL_DEPOSIT_STATUSES = {
    DepositStatus.PAID.value,
    DepositStatus.PARTIALLY_PAID.value,
    DepositStatus.EXPIRED.value,
}


class TransactionType(str, Enum):
    DEPOSIT = "deposit"
    TRANSFER_OUT = "transfer_out"
    TRANSFER_IN = "transfer_in"
    PURCHASE = "purchase"


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: f"acc_{uuid4().hex[:16]}",
    )
    api_key_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
        nullable=False,
    )
    balance_usd: Mapped[Decimal] = mapped_column(
        Numeric(precision=18, scale=2),
        default=Decimal("0.00"),
        nullable=False,
    )
    balance_credits: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    deposits: Mapped[list["Deposit"]] = relationship(
        "Deposit",
        back_populates="account",
        cascade="all, delete-orphan",
    )
    transactions: Mapped[list["Transaction"]] = relationship(
        "Transaction",
        back_populates="account",
        cascade="all, delete-orphan",
    )


class Deposit(Base):
    __tablename__ = "deposits"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: f"dep_{uuid4().hex[:16]}",
    )
    account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    invoice_id: Mapped[str | None] = mapped_column(
        String(64),
        unique=True,
        index=True,
        nullable=True,
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=18, scale=2),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default=DepositStatus.PENDING.value,
        index=True,
        nullable=False,
    )
    fee: Mapped[Decimal | None] = mapped_column(
        Numeric(precision=18, scale=2),
        nullable=True,
    )
    credited_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(precision=18, scale=2),
        nullable=True,
    )
    pay_url: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    account: Mapped[Account] = relationship("Account", back_populates="deposits")


class ProcessedWebhook(Base):
    """Tracks processed webhook events to guarantee idempotency and avoid double crediting."""
    __tablename__ = "processed_webhooks"

    event_id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )
    invoice_id: Mapped[str] = mapped_column(
        String(64),
        index=True,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    paid_amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=18, scale=2),
        nullable=False,
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class IdempotencyRecord(Base):
    """Stores executed transfer requests by Idempotency-Key.

    Guarantees:
    - Same key + same body -> return stored response.
    - Same key + different body -> return 409 Conflict.
    """
    __tablename__ = "idempotency_records"

    idempotency_key: Mapped[str] = mapped_column(
        String(128),
        primary_key=True,
    )
    account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    request_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    response_status_code: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    response_body: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class Transaction(Base):
    """Auditable ledger of balance operations for each account."""
    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: f"txn_{uuid4().hex[:16]}",
    )
    account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    type: Mapped[str] = mapped_column(
        String(32),
        index=True,
        nullable=False,
    )
    amount_usd: Mapped[Decimal] = mapped_column(
        Numeric(precision=18, scale=2),
        default=Decimal("0.00"),
        nullable=False,
    )
    amount_credits: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    balance_usd_after: Mapped[Decimal] = mapped_column(
        Numeric(precision=18, scale=2),
        nullable=False,
    )
    balance_credits_after: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    description: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    reference_id: Mapped[str | None] = mapped_column(
        String(64),
        index=True,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
        nullable=False,
    )

    account: Mapped[Account] = relationship("Account", back_populates="transactions")
