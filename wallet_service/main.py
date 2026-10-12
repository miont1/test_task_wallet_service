from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from wallet_service.api.v1.accounts import router as accounts_router
from wallet_service.api.v1.deposits import router as deposits_router
from wallet_service.api.v1.purchases import router as purchases_router
from wallet_service.api.v1.reconciliation import router as reconciliation_router
from wallet_service.api.v1.transactions import router as transactions_router
from wallet_service.api.v1.transfers import router as transfers_router
from wallet_service.api.v1.webhooks import router as webhooks_router
from wallet_service.config import get_settings
from wallet_service.core.errors import AppError
from wallet_service.core.rate_limiter import rate_limiter

EXEMPT_RATE_LIMIT_PREFIXES = ("/v1/webhooks", "/health", "/docs", "/openapi.json")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manages application startup and shutdown lifecycle.

    Initializes a shared HTTP client pool for outbound provider requests.
    """
    settings = get_settings()
    timeout = httpx.Timeout(settings.provider_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout) as client:
        app.state.http_client = client
        yield


app = FastAPI(
    title="LedgerLite Wallet Service",
    description="Internal USD ledger, credit purchasing and payment processing system.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def rate_limit_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    # 1. Only POST requests are rate limited
    if request.method != "POST":
        return await call_next(request)

    # 2. Exclude exempt endpoints (e.g. payment provider webhook)
    path = request.url.path
    if any(path.startswith(prefix) for prefix in EXEMPT_RATE_LIMIT_PREFIXES):
        return await call_next(request)

    # 3. Only rate limit requests that identify with an API key
    api_key = request.headers.get("X-API-Key")
    if not api_key:
        return await call_next(request)

    # 4. Check rate limiter (max 30 POST / min)
    is_limited, retry_after = rate_limiter.is_rate_limited(api_key)
    if is_limited:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(retry_after)},
            content={
                "error": {
                    "code": "rate_limit_exceeded",
                    "message": "Rate limit exceeded. Maximum 30 POST requests per minute allowed.",
                    "details": {
                        "limit": 30,
                        "retry_after": retry_after,
                    },
                }
            },
        )

    return await call_next(request)


@app.exception_handler(AppError)
async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
    content = {
        "error": {
            "code": exc.code,
            "message": exc.message,
            "details": jsonable_encoder(exc.details),
        }
    }
    return JSONResponse(status_code=exc.status_code, content=content)


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
        content={
            "error": {"code": "http_error", "message": str(exc.detail), "details": {}}
        },
    )


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(accounts_router)
app.include_router(deposits_router)
app.include_router(purchases_router)
app.include_router(transactions_router)
app.include_router(transfers_router)
app.include_router(webhooks_router)
app.include_router(reconciliation_router)
