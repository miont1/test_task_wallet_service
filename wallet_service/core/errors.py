from typing import Any

from fastapi import status


class AppError(Exception):
    """Base application exception with error code, message and details."""

    def __init__(
        self,
        message: str,
        code: str = "bad_request",
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}


class UnauthorizedError(AppError):
    def __init__(
        self, message: str = "Unauthorized", code: str = "unauthorized"
    ) -> None:
        super().__init__(
            message=message,
            code=code,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


class NotFoundError(AppError):
    def __init__(
        self, message: str = "Resource not found", code: str = "not_found"
    ) -> None:
        super().__init__(
            message=message,
            code=code,
            status_code=status.HTTP_404_NOT_FOUND,
        )


class ConflictError(AppError):
    def __init__(
        self,
        message: str = "Conflict",
        code: str = "conflict",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code=code,
            status_code=status.HTTP_409_CONFLICT,
            details=details,
        )


class InsufficientFundsError(AppError):
    def __init__(
        self,
        message: str = "Insufficient funds for this operation",
        code: str = "insufficient_funds",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code=code,
            status_code=status.HTTP_400_BAD_REQUEST,
            details=details,
        )


class ProviderTimeoutError(AppError):
    def __init__(
        self,
        message: str = "Payment provider request timed out",
        code: str = "provider_timeout",
    ) -> None:
        super().__init__(
            message=message,
            code=code,
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        )


class ProviderUnavailableError(AppError):
    def __init__(
        self,
        message: str = "Payment provider is currently unreachable",
        code: str = "provider_unavailable",
    ) -> None:
        super().__init__(
            message=message,
            code=code,
            status_code=status.HTTP_502_BAD_GATEWAY,
        )


class ProviderBadResponseError(AppError):
    def __init__(
        self,
        message: str = "Payment provider returned an invalid or error response",
        code: str = "provider_error",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code=code,
            status_code=status.HTTP_502_BAD_GATEWAY,
            details=details,
        )
