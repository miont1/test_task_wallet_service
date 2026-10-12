import re
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any
from uuid import uuid4

from pydantic import (
    BaseModel,
    BeforeValidator,
    Field,
    PlainSerializer,
    field_validator,
    model_validator,
)


class InvoiceStatus(str, Enum):
    PENDING = "pending"
    PAID = "paid"
    PARTIALLY_PAID = "partially_paid"
    EXPIRED = "expired"


FINAL_STATUSES = {
    InvoiceStatus.PAID,
    InvoiceStatus.PARTIALLY_PAID,
    InvoiceStatus.EXPIRED,
}

MONEY_REGEX = re.compile(r"^\d+\.\d{2}$")


def validate_money_amount(value: Any) -> Decimal:
    """Strictly validates money input:

    - When received from JSON: must be a string (e.g. '10.00'). Floats/ints raise TypeError (422).
    - In Python: can be str or Decimal.
    - Must have at most/exactly two decimal places and be non-negative.
    """
    if isinstance(value, Decimal):
        if value < Decimal("0.00"):
            raise ValueError("Money amount cannot be negative")
        if value.as_tuple().exponent < -2:
            raise ValueError("Money amount cannot have more than two decimal places")
        return value

    if not isinstance(value, str):
        raise TypeError("Money amount must be provided as a string (e.g. '10.00')")
    if not MONEY_REGEX.match(value):
        raise ValueError("Money amount must have exactly two decimal places (e.g. '10.00')")
    dec = Decimal(value)
    if dec < Decimal("0.00"):
        raise ValueError("Money amount cannot be negative")
    return dec


def serialize_money_amount(value: Decimal) -> str:
    """Serializes Decimal back into standard 2-decimal string format for JSON."""
    return f"{value:.2f}"


# Custom Money type: in Python it is Decimal, in JSON it is strictly string "10.00"
Money = Annotated[
    Decimal,
    BeforeValidator(validate_money_amount),
    PlainSerializer(serialize_money_amount, return_type=str, when_used="json"),
]


class InvoiceRecord(BaseModel):
    invoice_id: str
    amount: Decimal
    paid_amount: Decimal = Decimal("0.00")
    currency: str = "USD"
    external_id: str
    callback_url: str
    status: InvoiceStatus = InvoiceStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class InvoiceCreateRequest(BaseModel):
    amount: Money
    currency: str = Field(default="USD")
    external_id: str = Field(..., description="ID of the deposit or external reference")
    callback_url: str = Field(..., description="Webhook URL to be notified upon payment")

    @field_validator("amount")
    @classmethod
    def validate_positive_amount(cls, v: Decimal) -> Decimal:
        if v <= Decimal("0.00"):
            raise ValueError("Invoice amount must be greater than 0.00")
        return v

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        if v.upper() != "USD":
            raise ValueError("Only USD is currently supported")
        return v.upper()


class InvoiceResponse(BaseModel):
    invoice_id: str
    status: InvoiceStatus
    pay_url: str


class InvoiceDetailResponse(BaseModel):
    invoice_id: str
    status: InvoiceStatus
    amount: Money
    paid_amount: Money
    currency: str
    external_id: str
    callback_url: str
    created_at: str
    updated_at: str


class SimulateRequest(BaseModel):
    status: InvoiceStatus
    paid_amount: Money
    deliver_webhook: bool = True
    duplicate: bool = False

    @field_validator("status")
    @classmethod
    def validate_simulate_status(cls, v: InvoiceStatus) -> InvoiceStatus:
        if v not in FINAL_STATUSES:
            raise ValueError("Simulated status must be one of: paid, partially_paid, expired")
        return v

    @model_validator(mode="after")
    def validate_paid_amount_consistency(self) -> "SimulateRequest":
        if self.status == InvoiceStatus.EXPIRED and self.paid_amount > Decimal("0.00"):
            raise ValueError("Expired invoice paid_amount must be '0.00'")
        return self


class WebhookPayload(BaseModel):
    event_id: str = Field(default_factory=lambda: f"evt_{uuid4().hex[:16]}")
    invoice_id: str
    status: InvoiceStatus
    paid_amount: Money
    occurred_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


class SimulateResponse(BaseModel):
    invoice_id: str
    status: InvoiceStatus
    paid_amount: Money
    webhook_delivered: bool
    webhook_duplicate: bool
    webhook_status_codes: list[int] = Field(default_factory=list)
