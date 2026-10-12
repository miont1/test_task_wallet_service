import asyncio
from decimal import Decimal

from sqlalchemy import select

from wallet_service.core.security import hash_api_key
from wallet_service.db.models import Account, Transaction, TransactionType
from wallet_service.db.session import async_session_factory, init_db

INITIAL_USERS = [
    {
        "name": "Alice",
        "api_key": "wlt_alice_test_key_12345",
        "balance_usd": Decimal("100.00"),
        "balance_credits": 50,
    },
    {
        "name": "Bob",
        "api_key": "wlt_bob_test_key_67890",
        "balance_usd": Decimal("50.00"),
        "balance_credits": 0,
    },
    {
        "name": "Charlie",
        "api_key": "wlt_charlie_test_key_54321",
        "balance_usd": Decimal("0.00"),
        "balance_credits": 0,
    },
]


async def seed_data() -> None:
    print("Initializing database tables if needed...")
    await init_db()

    async with async_session_factory() as session:
        for user_info in INITIAL_USERS:
            key_hash = hash_api_key(user_info["api_key"])
            stmt = select(Account).where(Account.api_key_hash == key_hash)
            existing = await session.scalar(stmt)

            if existing is None:
                account = Account(
                    api_key_hash=key_hash,
                    balance_usd=user_info["balance_usd"],
                    balance_credits=user_info["balance_credits"],
                )
                session.add(account)
                await session.flush()

                # Add initial transaction record if balance > 0
                if (
                    user_info["balance_usd"] > Decimal("0.00")
                    or user_info["balance_credits"] > 0
                ):
                    txn = Transaction(
                        account_id=account.id,
                        type=TransactionType.DEPOSIT.value,
                        amount_usd=user_info["balance_usd"],
                        amount_credits=user_info["balance_credits"],
                        balance_usd_after=user_info["balance_usd"],
                        balance_credits_after=user_info["balance_credits"],
                        description=f"Initial seed balance for {user_info['name']}",
                        reference_id="seed_initial",
                    )
                    session.add(txn)

                print(
                    f"Created account for {user_info['name']} (ID: {account.id}) with API Key: {user_info['api_key']}"
                )
            else:
                print(
                    f"Account for {user_info['name']} already exists (ID: {existing.id})"
                )

        await session.commit()
    print("Database seeding completed successfully.")


if __name__ == "__main__":
    asyncio.run(seed_data())
