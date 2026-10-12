from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from wallet_service.api.v1.accounts import router as accounts_router
from wallet_service.core.errors import AppError

app = FastAPI(
    title="LedgerLite Wallet Service",
    description="Internal USD ledger, credit purchasing and payment processing system.",
    version="0.1.0",
)


@app.exception_handler(AppError)
async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
    content = {
        "error": {
            "code": exc.code,
            "message": exc.message,
            "details": exc.details,
        }
    }
    return JSONResponse(status_code=exc.status_code, content=content)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
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
        content={"error": {"code": "http_error", "message": str(exc.detail), "details": {}}},
    )


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(accounts_router)
