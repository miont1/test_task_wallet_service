import threading
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from provider_mock.exceptions import InvoiceAlreadyFinalError, InvoiceNotFoundError
from provider_mock.models import FINAL_STATUSES, InvoiceRecord, InvoiceStatus


class InvoiceStore:
    def __init__(self) -> None:
        self._invoices: dict[str, InvoiceRecord] = {}
        self._lock = threading.Lock()

    def create(
        self,
        amount: Decimal,
        currency: str,
        external_id: str,
        callback_url: str,
    ) -> InvoiceRecord:
        invoice_id = f"inv_{uuid4().hex[:16]}"
        record = InvoiceRecord(
            invoice_id=invoice_id,
            amount=amount,
            paid_amount=Decimal("0.00"),
            currency=currency,
            external_id=external_id,
            callback_url=callback_url,
            status=InvoiceStatus.PENDING,
        )
        with self._lock:
            self._invoices[invoice_id] = record
        return record

    def get(self, invoice_id: str) -> InvoiceRecord | None:
        with self._lock:
            return self._invoices.get(invoice_id, None)

    def update_status(
        self,
        invoice_id: str,
        new_status: InvoiceStatus,
        paid_amount: Decimal,
    ) -> InvoiceRecord:
        with self._lock:
            record = self._invoices.get(invoice_id)
            if record is None:
                raise InvoiceNotFoundError(invoice_id=invoice_id)

            if record.status in FINAL_STATUSES:
                raise InvoiceAlreadyFinalError(
                    invoice_id=invoice_id,
                    current_status=record.status.value,
                )

            record.status = new_status
            record.paid_amount = paid_amount
            record.updated_at = datetime.now(UTC)
            return record

    def clear(self) -> None:
        with self._lock:
            self._invoices.clear()


# Default singleton instance for the service
invoice_store = InvoiceStore()
