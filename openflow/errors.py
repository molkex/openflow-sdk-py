"""Exception hierarchy for the openflow SDK."""
from __future__ import annotations

from typing import Any, Optional


class OpenFlowError(Exception):
    """Base error for the openflow SDK."""

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        body: Any = None,
        request_id: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.body = body
        self.request_id = request_id

    def __str__(self) -> str:
        base = self.message
        if self.status_code is not None:
            base = f"[{self.status_code}] {base}"
        if self.request_id:
            base = f"{base} (request_id={self.request_id})"
        return base


class AuthError(OpenFlowError):
    """401/403 — missing or invalid API key."""


class QuotaError(OpenFlowError):
    """429 — quota/rate-limit exceeded."""


class UpstreamError(OpenFlowError):
    """5xx — upstream LLM/Flow provider failed."""


class BadRequestError(OpenFlowError):
    """400 — invalid request shape."""


def error_from_response(status_code: int, body: Any, request_id: Optional[str] = None) -> OpenFlowError:
    message = _extract_message(body) or f"HTTP {status_code}"
    if status_code in (401, 403):
        return AuthError(message, status_code=status_code, body=body, request_id=request_id)
    if status_code == 429:
        return QuotaError(message, status_code=status_code, body=body, request_id=request_id)
    if 500 <= status_code < 600:
        return UpstreamError(message, status_code=status_code, body=body, request_id=request_id)
    if 400 <= status_code < 500:
        return BadRequestError(message, status_code=status_code, body=body, request_id=request_id)
    return OpenFlowError(message, status_code=status_code, body=body, request_id=request_id)


def _extract_message(body: Any) -> Optional[str]:
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            msg = err.get("message")
            if isinstance(msg, str):
                return msg
        if isinstance(err, str):
            return err
        for key in ("message", "detail", "error_description"):
            v = body.get(key)
            if isinstance(v, str):
                return v
    if isinstance(body, str):
        return body
    return None
