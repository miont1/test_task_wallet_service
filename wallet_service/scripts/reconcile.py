import argparse
import asyncio

import httpx

from wallet_service.config import get_settings
from wallet_service.db.session import async_session_factory
from wallet_service.services.provider_client import ProviderClient
from wallet_service.services.reconciliation_service import run_reconciliation


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reconcile pending deposits against payment provider."
    )
    parser.add_argument(
        "--minutes",
        type=int,
        default=5,
        help="Reconcile pending deposits older than N minutes (default: 5)",
    )
    args = parser.parse_args()

    settings = get_settings()
    timeout = httpx.Timeout(settings.provider_timeout_seconds)

    async with httpx.AsyncClient(timeout=timeout) as client:
        provider_client = ProviderClient(client=client, settings=settings)
        async with async_session_factory() as session:
            result = await run_reconciliation(
                session=session,
                provider_client=provider_client,
                older_than_minutes=args.minutes,
            )
            print(f"Scanned {result.scanned_count} pending deposits.")
            print(f"Reconciled {result.reconciled_count} deposits.")
            for item in result.details:
                print(
                    f" - Deposit {item.deposit_id} ({item.invoice_id}): {item.old_status} -> {item.new_status}, credited: {item.credited_amount} USD"
                )


if __name__ == "__main__":
    asyncio.run(main())
