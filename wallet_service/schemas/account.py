from pydantic import BaseModel, Field

from wallet_service.services.money import Money


class AccountCreateResponse(BaseModel):
    account_id: str = Field(
        description="Unique identifier of the newly created account"
    )
    api_key: str = Field(
        description="Secret API key. Shown only once upon registration!"
    )
    balance_usd: Money = Field(description="Initial USD balance")
    balance_credits: int = Field(description="Initial credits balance")


class AccountMeResponse(BaseModel):
    account_id: str = Field(description="Account unique identifier")
    balance_usd: Money = Field(description="Current balance in USD")
    balance_credits: int = Field(description="Current balance in credits")
