from typing import Any, Optional

MISSING_CREDENTIALS = "MISSING_CREDENTIALS"
AUTH_FAILED = "AUTH_FAILED"
CONNECTION_ERROR = "CONNECTION_ERROR"
NOT_INITIALIZED = "NOT_INITIALIZED"
UNKNOWN = "UNKNOWN"

ErrorCode = str


def structured_error(
    code: ErrorCode,
    message: str,
    *,
    retryable: bool,
    details: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build a structured error dict with a backward-compatible ``error`` key."""
    payload: dict[str, Any] = {
        "code": code,
        "message": message,
        "retryable": retryable,
        "error": message,
    }
    if details is not None:
        payload["details"] = details
    return payload
