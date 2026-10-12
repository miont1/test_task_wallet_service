from decimal import Decimal

import pytest
from pydantic import BaseModel, ValidationError

from wallet_service.services.money import (
    Money,
    calculate_credited_amount,
    calculate_credits_cost,
    calculate_provider_fee,
    validate_transfer_amount,
)


@pytest.mark.parametrize(
    ("paid", "expected_fee", "expected_credited"),
    [
        (Decimal("10.00"), Decimal("0.15"), Decimal("9.85")),
        (Decimal("0.99"), Decimal("0.01"), Decimal("0.98")),
        (Decimal("33.33"), Decimal("0.50"), Decimal("32.83")),
    ],
)
def test_provider_fee_specification_table(
    paid: Decimal,
    expected_fee: Decimal,
    expected_credited: Decimal,
) -> None:
    """Verifies the exact provider fee and credited amounts specified in the test task table."""
    fee = calculate_provider_fee(paid)
    calculated_fee, credited = calculate_credited_amount(paid)

    assert fee == expected_fee
    assert calculated_fee == expected_fee
    assert credited == expected_credited


@pytest.mark.parametrize(
    ("credits_count", "expected_price"),
    [
        (333, Decimal("33.30")),
        (507, Decimal("48.17")),
        (1005, Decimal("87.94")),
    ],
)
def test_credit_pricing_specification_table(
    credits_count: int,
    expected_price: Decimal,
) -> None:
    """Verifies the exact credit tier discount calculations specified in the test task table."""
    price = calculate_credits_cost(credits_count)
    assert price == expected_price


def test_credit_pricing_tier_boundaries() -> None:
    # 499 credits (no discount): 499 * 0.10 = 49.90
    assert calculate_credits_cost(499) == Decimal("49.90")

    # 500 credits (5% discount): 500 * 0.10 * 0.95 = 47.50
    assert calculate_credits_cost(500) == Decimal("47.50")

    # 999 credits (5% discount): 999 * 0.10 * 0.95 = 94.905 -> 94.91 (ROUND_HALF_UP)
    assert calculate_credits_cost(999) == Decimal("94.91")

    # 1000 credits (12.5% discount): 1000 * 0.10 * 0.875 = 87.50
    assert calculate_credits_cost(1000) == Decimal("87.50")


def test_credit_pricing_invalid_count() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        calculate_credits_cost(0)

    with pytest.raises(ValueError, match="positive integer"):
        calculate_credits_cost(-5)


def test_validate_transfer_amount() -> None:
    # Valid transfers (>= 0.01)
    validate_transfer_amount(Decimal("0.01"))
    validate_transfer_amount(Decimal("10.00"))

    # Invalid transfers (< 0.01)
    with pytest.raises(ValueError, match="Minimum transfer amount"):
        validate_transfer_amount(Decimal("0.00"))

    with pytest.raises(ValueError, match="Minimum transfer amount"):
        validate_transfer_amount(Decimal("-1.00"))


class SampleModel(BaseModel):
    amount: Money


def test_money_validation_strictness() -> None:
    # Valid string
    m = SampleModel.model_validate({"amount": "10.00"})
    assert m.amount == Decimal("10.00")
    assert m.model_dump(mode="json") == {"amount": "10.00"}

    # Invalid: Float instead of string -> ValidationError (422)
    with pytest.raises(ValidationError):
        SampleModel.model_validate({"amount": 10.0})

    # Invalid: Integer instead of string
    with pytest.raises(ValidationError):
        SampleModel.model_validate({"amount": 10})

    # Invalid: 1 decimal place
    with pytest.raises(ValidationError):
        SampleModel.model_validate({"amount": "10.5"})

    # Invalid: 3 decimal places
    with pytest.raises(ValidationError):
        SampleModel.model_validate({"amount": "10.005"})

    # Invalid: Negative
    with pytest.raises(ValidationError):
        SampleModel.model_validate({"amount": "-10.00"})
