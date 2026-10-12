import hashlib
import hmac
import time

from wallet_service.core.errors import UnauthorizedError


def compute_webhook_signature(secret: str, timestamp: int | str, raw_body: str) -> str:
    """Computes HMAC-SHA256 signature according to specification formula:

    HMAC-SHA256(secret, f"{timestamp}.{raw_body}")
    """
    message = f"{timestamp}.{raw_body}".encode()
    return hmac.new(
        key=secret.encode("utf-8"),
        msg=message,
        digestmod=hashlib.sha256,
    ).hexdigest()


def verify_webhook_signature(
    secret: str,
    timestamp_header: str | None,
    signature_header: str | None,
    raw_body_bytes: bytes,
    tolerance_seconds: int = 300,
    current_time: float | None = None,
) -> None:
    """Verifies incoming webhook freshness (tolerance 5 min) and cryptographic signature.

    Raises UnauthorizedError (HTTP 401) on missing headers, expired timestamp or invalid signature.
    """
    if not timestamp_header:
        raise UnauthorizedError(
            message="Missing X-Timestamp header",
            code="missing_timestamp",
        )

    if not signature_header:
        raise UnauthorizedError(
            message="Missing X-Signature header",
            code="missing_signature",
        )

    # 1. Verify timestamp format and freshness
    try:
        timestamp_int = int(timestamp_header)
    except ValueError as exc:
        raise UnauthorizedError(
            message="Invalid X-Timestamp header format",
            code="invalid_timestamp",
        ) from exc

    now = current_time if current_time is not None else time.time()
    drift = abs(now - timestamp_int)
    if drift > tolerance_seconds:
        raise UnauthorizedError(
            message=f"Webhook timestamp expired or drifted beyond tolerance ({tolerance_seconds}s)",
            code="timestamp_expired",
        )

    # 2. Extract provided hex signature
    if not signature_header.startswith("sha256="):
        raise UnauthorizedError(
            message="Invalid X-Signature format (expected 'sha256=<hex>')",
            code="invalid_signature_format",
        )

    provided_hex = signature_header.split("sha256=", 1)[1]

    # 3. Compute expected signature and compare securely
    try:
        raw_body_str = raw_body_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UnauthorizedError(
            message="Invalid UTF-8 payload in webhook",
            code="invalid_payload_encoding",
        ) from exc

    expected_hex = compute_webhook_signature(
        secret=secret,
        timestamp=timestamp_int,
        raw_body=raw_body_str,
    )

    if not hmac.compare_digest(expected_hex, provided_hex):
        raise UnauthorizedError(
            message="Invalid webhook signature",
            code="invalid_signature",
        )
