from pydantic import BaseModel, Field

from wallet_service.services.money import Money


class ProviderWebhookPayload(BaseModel):
    event_id: str = Field(description="Unique event identifier from payment provider")
    invoice_id: str = Field(description="Invoice identifier assigned by provider")
    status: str = Field(description="New status of invoice (paid, partially_paid, expired)")
    paid_amount: Money = Field(description="Amount actually paid in USD")
    occurred_at: str = Field(description="ISO-8601 timestamp of payment event")
