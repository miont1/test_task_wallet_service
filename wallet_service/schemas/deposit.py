from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from wallet_service.services.money import Money


class DepositCreateRequest(BaseModel):
    amount: Money = Field(
        description="Deposit amount in USD as a string with exactly 2 decimal places (e.g. '10.00')"
    )

    @field_validator("amount")
    @classmethod
    def validate_positive_amount(cls, v: Decimal) -> Decimal:
        if v <= Decimal("0.00"):
            raise ValueError("Deposit amount must be greater than 0.00")
        return v


class DepositCreateResponse(BaseModel):
    deposit_id: str = Field(description="Unique internal deposit reference ID")
    status: str = Field(description="Current status of the deposit (pending)")
    amount: Money = Field(description="Requested deposit amount")
    pay_url: str = Field(description="URL to complete payment via payment provider")
