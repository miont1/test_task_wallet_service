from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from provider_mock.config import Settings, get_settings
from provider_mock.dependencies import (
    get_invoice_store,
    get_webhook_dispatcher,
    verify_bearer_token,
)
from provider_mock.exceptions import InvoiceAlreadyFinalError, InvoiceNotFoundError
from provider_mock.models import (
    InvoiceCreateRequest,
    InvoiceDetailResponse,
    InvoiceResponse,
    SimulateRequest,
    SimulateResponse,
    WebhookPayload,
)
from provider_mock.storage import InvoiceStore
from provider_mock.webhook import WebhookDispatcher


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manages the lifespan of provider-mock.

    Initializes a shared HTTP client on startup and closes it on shutdown.
    """
    settings = get_settings()
    timeout = httpx.Timeout(settings.webhook_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout) as client:
        app.state.http_client = client
        yield


app = FastAPI(
    title="LedgerLite Payment Provider Mock",
    description="Mock payment provider with invoice creation, status simulation, and signed webhooks.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.exception_handler(InvoiceNotFoundError)
async def handle_invoice_not_found(
    _: Request, exc: InvoiceNotFoundError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.exception_handler(InvoiceAlreadyFinalError)
async def handle_invoice_already_final(
    _: Request, exc: InvoiceAlreadyFinalError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": {
                    "invoice_id": exc.invoice_id,
                    "current_status": exc.current_status,
                },
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "error": {
                "code": "validation_error",
                "message": "Invalid request payload or parameters",
                "details": jsonable_encoder(exc.errors()),
            }
        },
    )


@app.exception_handler(HTTPException)
async def handle_http_exception(_: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": "http_error", "message": str(exc.detail)}},
    )


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/invoices",
    response_model=InvoiceResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Invoices"],
)
async def create_invoice(
    payload: InvoiceCreateRequest,
    store: Annotated[InvoiceStore, Depends(get_invoice_store)],
    settings: Annotated[Settings, Depends(get_settings)],
    _: Annotated[str, Depends(verify_bearer_token)],
) -> InvoiceResponse:
    """Creates a new payment invoice in pending status."""
    record = store.create(
        amount=payload.amount,
        currency=payload.currency,
        external_id=payload.external_id,
        callback_url=payload.callback_url,
    )
    pay_url = f"{settings.base_pay_url.rstrip('/')}/{record.invoice_id}"
    return InvoiceResponse(
        invoice_id=record.invoice_id,
        status=record.status,
        pay_url=pay_url,
    )


@app.get(
    "/invoices/{invoice_id}",
    response_model=InvoiceDetailResponse,
    tags=["Invoices"],
)
async def get_invoice(
    invoice_id: str,
    store: Annotated[InvoiceStore, Depends(get_invoice_store)],
    _: Annotated[str, Depends(verify_bearer_token)],
) -> InvoiceDetailResponse:
    """Retrieves the current state and paid_amount of an invoice."""
    record = store.get(invoice_id)
    if record is None:
        raise InvoiceNotFoundError(invoice_id=invoice_id)

    return InvoiceDetailResponse(
        invoice_id=record.invoice_id,
        status=record.status,
        amount=record.amount,
        paid_amount=record.paid_amount,
        currency=record.currency,
        external_id=record.external_id,
        callback_url=record.callback_url,
        created_at=record.created_at.isoformat(),
        updated_at=record.updated_at.isoformat(),
    )


@app.post(
    "/invoices/{invoice_id}/simulate",
    response_model=SimulateResponse,
    tags=["Simulation"],
)
async def simulate_invoice(
    invoice_id: str,
    payload: SimulateRequest,
    store: Annotated[InvoiceStore, Depends(get_invoice_store)],
    dispatcher: Annotated[WebhookDispatcher, Depends(get_webhook_dispatcher)],
    _: Annotated[str, Depends(verify_bearer_token)],
) -> SimulateResponse:
    """Simulates an invoice status change and optionally dispatches signed webhook(s)."""
    # 1. Update invoice state (checks existence and final status immutability)
    record = store.update_status(
        invoice_id=invoice_id,
        new_status=payload.status,
        paid_amount=payload.paid_amount,
    )

    webhook_delivered = False
    webhook_status_codes: list[int] = []

    # 2. Dispatch webhook if requested
    if payload.deliver_webhook:
        webhook_payload = WebhookPayload(
            invoice_id=record.invoice_id,
            status=record.status,
            paid_amount=record.paid_amount,
        )
        delivery_result = await dispatcher.dispatch(
            callback_url=record.callback_url,
            payload=webhook_payload,
            duplicate=payload.duplicate,
        )
        webhook_delivered = delivery_result.is_delivered
        webhook_status_codes = delivery_result.status_codes

    return SimulateResponse(
        invoice_id=record.invoice_id,
        status=record.status,
        paid_amount=record.paid_amount,
        webhook_delivered=webhook_delivered,
        webhook_duplicate=payload.duplicate,
        webhook_status_codes=webhook_status_codes,
    )
