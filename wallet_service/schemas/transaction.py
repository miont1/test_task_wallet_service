from pydantic import BaseModel, Field

from wallet_service.services.money import Money


class TransactionItem(BaseModel):
    id: str = Field(description="Unique transaction identifier")
    type: str = Field(
        description="Operation type: deposit, transfer_out, transfer_in, purchase"
    )
    amount_usd: Money = Field(description="USD amount involved in the transaction")
    amount_credits: int = Field(description="Credit amount involved in the transaction")
    balance_usd_after: Money = Field(
        description="Account USD balance after transaction"
    )
    balance_credits_after: int = Field(
        description="Account credit balance after transaction"
    )
    description: str = Field(description="Human-readable transaction description")
    reference_id: str | None = Field(
        default=None, description="Associated entity ID (deposit, transfer, purchase)"
    )
    created_at: str = Field(description="ISO-8601 transaction creation timestamp")


class TransactionListResponse(BaseModel):
    items: list[TransactionItem] = Field(
        description="List of transactions for the requested page"
    )
    next_cursor: str | None = Field(
        default=None, description="Cursor for fetching the next page of transactions"
    )
    has_more: bool = Field(
        description="True if there are additional transactions following this page"
    )
