import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any

from pydantic import BeforeValidator, PlainSerializer

MONEY_REGEX = re.compile(r"^\d+\.\d{2}$")
CENT = Decimal("0.01")
MIN_TRANSFER_AMOUNT = Decimal("0.01")
PROVIDER_FEE_RATE = Decimal("0.015")  # 1.5%

BASE_CREDIT_PRICE = Decimal("0.10")  # 0.10 USD per credit
CREDIT_TIER_1_THRESHOLD = 500
CREDIT_TIER_1_DISCOUNT = Decimal("0.05")   # 5% discount
CREDIT_TIER_2_THRESHOLD = 1000
CREDIT_TIER_2_DISCOUNT = Decimal("0.125")  # 12.5% discount


def quantize_cents(amount: Decimal) -> Decimal:
    """Rounds a decimal amount to cents (2 decimal places) using ROUND_HALF_UP."""
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def validate_money_amount(value: Any) -> Decimal:
    """Strictly validates money input:

    - When received from JSON: must be a string (e.g. '10.00'). Numbers/floats raise ValueError (422).
    - In Python: can be str or Decimal.
    - Must have at most/exactly two decimal places and be non-negative.
    """
    if isinstance(value, Decimal):
        if value < Decimal("0.00"):
            raise ValueError("Money amount cannot be negative")
        if value.as_tuple().exponent < -2:
            raise ValueError("Money amount cannot have more than two decimal places")
        return value

    if not isinstance(value, str):
        raise ValueError("Money amount must be provided as a string (e.g. '10.00')")  # noqa: TRY004
    if not MONEY_REGEX.match(value):
        raise ValueError("Money amount must have exactly two decimal places (e.g. '10.00')")
    return Decimal(value)


def serialize_money_amount(value: Decimal) -> str:
    return f"{value:.2f}"


Money = Annotated[
    Decimal,
    BeforeValidator(validate_money_amount),
    PlainSerializer(serialize_money_amount, return_type=str, when_used="json"),
]


def calculate_provider_fee(paid_amount: Decimal) -> Decimal:
    """Calculates provider fee: 1.5% of paid amount, rounded to cents with ROUND_HALF_UP."""
    if paid_amount <= Decimal("0.00"):
        return Decimal("0.00")
    raw_fee = paid_amount * PROVIDER_FEE_RATE
    return quantize_cents(raw_fee)


def calculate_credited_amount(paid_amount: Decimal) -> tuple[Decimal, Decimal]:
    """Returns (fee, credited_amount) where credited_amount = paid_amount - fee."""
    fee = calculate_provider_fee(paid_amount)
    credited = paid_amount - fee
    return fee, credited


def calculate_credits_cost(credits_count: int) -> Decimal:
    """Calculates the USD price to purchase a given number of credits:

    - Base price: 0.10 USD per credit
    - From 500 credits: 5% discount
    - From 1000 credits: 12.5% discount
    - Final price rounded to cents with ROUND_HALF_UP
    """
    if credits_count <= 0:
        raise ValueError("Credits amount must be a positive integer greater than 0")

    base_cost = Decimal(credits_count) * BASE_CREDIT_PRICE

    if credits_count >= CREDIT_TIER_2_THRESHOLD:
        discount_rate = CREDIT_TIER_2_DISCOUNT
    elif credits_count >= CREDIT_TIER_1_THRESHOLD:
        discount_rate = CREDIT_TIER_1_DISCOUNT
    else:
        discount_rate = Decimal("0.00")

    final_cost = base_cost * (Decimal("1.00") - discount_rate)
    return quantize_cents(final_cost)


def validate_transfer_amount(amount: Decimal) -> None:
    """Validates that a transfer meets the minimum amount requirement (0.01 USD)."""
    if amount < MIN_TRANSFER_AMOUNT:
        raise ValueError(f"Minimum transfer amount is {MIN_TRANSFER_AMOUNT} USD")
