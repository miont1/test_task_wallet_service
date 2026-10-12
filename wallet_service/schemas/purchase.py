from pydantic import BaseModel, Field

from wallet_service.services.money import Money


class PurchaseCreateRequest(BaseModel):
    credits: int = Field(
        gt=0, description="Number of credits to purchase (must be greater than 0)"
    )


class PurchaseResponse(BaseModel):
    purchase_id: str = Field(description="Unique purchase identifier")
    account_id: str = Field(description="Account identifier")
    credits_purchased: int = Field(description="Number of credits added to balance")
    cost_usd: Money = Field(description="USD amount deducted for the purchase")
    balance_usd_after: Money = Field(description="Remaining USD balance after purchase")
    balance_credits_after: int = Field(description="New total credits balance")
    created_at: str = Field(description="ISO-8601 timestamp of the purchase")
