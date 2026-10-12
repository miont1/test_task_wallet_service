import base64
import json
from datetime import datetime

from fastapi import status

from wallet_service.core.errors import AppError


def encode_cursor(created_at: datetime, item_id: str) -> str:
    """Encodes created_at timestamp and item ID into an opaque URL-safe base64 cursor."""
    payload = {
        "t": created_at.isoformat(),
        "id": item_id,
    }
    json_bytes = json.dumps(payload).encode("utf-8")
    return base64.urlsafe_b64encode(json_bytes).decode("ascii")


def decode_cursor(cursor_str: str) -> tuple[datetime, str]:
    """Decodes a URL-safe base64 cursor into (created_at, item_id).

    Raises AppError (HTTP 400) if the cursor is malformed or invalid.
    """
    try:
        raw_bytes = base64.urlsafe_b64decode(cursor_str.encode("ascii"))
        payload = json.loads(raw_bytes.decode("utf-8"))
        timestamp = datetime.fromisoformat(payload["t"])
        item_id = str(payload["id"])
        return timestamp, item_id
    except Exception as exc:
        raise AppError(
            message="Invalid pagination cursor provided",
            code="invalid_cursor",
            status_code=status.HTTP_400_BAD_REQUEST,
        ) from exc
