from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from wallet_service.services.money import Money


class TransferCreateRequest(BaseModel):
    to_account_id: str = Field(min_length=1, description="Recipient account identifier")
    amount: Money = Field(description="Transfer amount in USD (minimum 0.01)")

    @field_validator("amount")
    @classmethod
    def validate_min_amount(cls, v: Decimal) -> Decimal:
        if v < Decimal("0.01"):
            raise ValueError("Transfer amount must be at least 0.01 USD")
        return v


class TransferResponse(BaseModel):
    transfer_id: str = Field(description="Unique transfer transaction identifier")
    from_account_id: str = Field(description="Sender account identifier")
    to_account_id: str = Field(description="Recipient account identifier")
    amount: Money = Field(description="Transferred amount in USD")
    from_balance_usd_after: Money = Field(
        description="Sender USD balance after transfer"
    )
    created_at: str = Field(description="ISO-8601 creation timestamp")
