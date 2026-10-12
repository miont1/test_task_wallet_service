from decimal import Decimal

import pytest

from provider_mock.exceptions import InvoiceAlreadyFinalError, InvoiceNotFoundError
from provider_mock.models import InvoiceStatus
from provider_mock.storage import InvoiceStore


def test_create_and_get_invoice(store: InvoiceStore) -> None:
    record = store.create(
        amount=Decimal("10.00"),
        currency="USD",
        external_id="dep_001",
        callback_url="http://callback.example/webhook",
    )
    assert record.invoice_id.startswith("inv_")
    assert record.status == InvoiceStatus.PENDING
    assert record.amount == Decimal("10.00")
    assert record.paid_amount == Decimal("0.00")
    assert record.external_id == "dep_001"

    retrieved = store.get(record.invoice_id)
    assert retrieved is not None
    assert retrieved.invoice_id == record.invoice_id


def test_get_nonexistent_invoice(store: InvoiceStore) -> None:
    assert store.get("nonexistent_id") is None


def test_update_status_success(store: InvoiceStore) -> None:
    record = store.create(
        amount=Decimal("20.00"),
        currency="USD",
        external_id="dep_002",
        callback_url="http://callback.example/webhook",
    )

    updated = store.update_status(
        invoice_id=record.invoice_id,
        new_status=InvoiceStatus.PAID,
        paid_amount=Decimal("20.00"),
    )
    assert updated.status == InvoiceStatus.PAID
    assert updated.paid_amount == Decimal("20.00")


@pytest.mark.parametrize("final_status", [
    InvoiceStatus.PAID,
    InvoiceStatus.PARTIALLY_PAID,
    InvoiceStatus.EXPIRED,
])
def test_final_status_is_immutable(store: InvoiceStore, final_status: InvoiceStatus) -> None:
    record = store.create(
        amount=Decimal("15.00"),
        currency="USD",
        external_id="dep_003",
        callback_url="http://callback.example/webhook",
    )

    store.update_status(
        invoice_id=record.invoice_id,
        new_status=final_status,
        paid_amount=Decimal("15.00") if final_status != InvoiceStatus.EXPIRED else Decimal("0.00"),
    )

    # Attempting to change state again must fail
    with pytest.raises(InvoiceAlreadyFinalError) as exc_info:
        store.update_status(
            invoice_id=record.invoice_id,
            new_status=InvoiceStatus.PAID,
            paid_amount=Decimal("15.00"),
        )
    assert exc_info.value.current_status == final_status.value


def test_update_nonexistent_invoice_raises_error(store: InvoiceStore) -> None:
    with pytest.raises(InvoiceNotFoundError):
        store.update_status(
            invoice_id="inv_not_exist",
            new_status=InvoiceStatus.PAID,
            paid_amount=Decimal("10.00"),
        )
