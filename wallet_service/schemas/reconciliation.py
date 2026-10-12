from pydantic import BaseModel, Field

from wallet_service.services.money import Money


class ReconciledDepositItem(BaseModel):
    deposit_id: str = Field(description="Deposit identifier")
    invoice_id: str = Field(description="Provider invoice identifier")
    account_id: str = Field(description="Account identifier credited")
    old_status: str = Field(description="Status before reconciliation")
    new_status: str = Field(description="New status after reconciliation")
    credited_amount: Money = Field(description="USD net amount credited")


class ReconciliationResponse(BaseModel):
    scanned_count: int = Field(description="Total number of pending deposits scanned")
    reconciled_count: int = Field(description="Number of deposits resolved and updated")
    details: list[ReconciledDepositItem] = Field(
        description="Details of reconciled deposits"
    )
