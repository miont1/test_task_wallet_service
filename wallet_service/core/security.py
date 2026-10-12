import hashlib
import secrets


def generate_api_key(prefix: str = "wlt_") -> str:
    """Generates a secure, random API key for user authentication."""
    random_part = secrets.token_urlsafe(32)
    return f"{prefix}{random_part}"


def hash_api_key(api_key: str) -> str:
    """Computes SHA-256 hash of API key.

    API keys are never stored in plaintext in the database.
    """
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()
