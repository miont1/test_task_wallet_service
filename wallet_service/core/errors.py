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
    def __init__(self, message: str = "Unauthorized", code: str = "unauthorized") -> None:
        super().__init__(
            message=message,
            code=code,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


class NotFoundError(AppError):
    def __init__(self, message: str = "Resource not found", code: str = "not_found") -> None:
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
