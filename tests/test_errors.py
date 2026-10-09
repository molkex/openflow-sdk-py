"""Error hierarchy and dispatch coverage."""
from __future__ import annotations

import pytest

from openflow.errors import (
    AuthError,
    BadRequestError,
    OpenFlowError,
    QuotaError,
    UpstreamError,
    error_from_response,
    _extract_message,
)


def test_str_without_status():
    err = OpenFlowError("boom")
    assert str(err) == "boom"


def test_str_with_status():
    err = OpenFlowError("boom", status_code=500)
    assert "[500]" in str(err)
    assert "boom" in str(err)


def test_str_with_request_id():
    err = OpenFlowError("boom", status_code=500, request_id="rid_7")
    s = str(err)
    assert "rid_7" in s and "[500]" in s


def test_dispatch_401_is_auth():
    e = error_from_response(401, {"error": {"message": "bad key"}})
    assert isinstance(e, AuthError)
    assert e.message == "bad key"
    assert e.status_code == 401


def test_dispatch_403_is_auth():
    e = error_from_response(403, None)
    assert isinstance(e, AuthError)


def test_dispatch_429_is_quota():
    e = error_from_response(429, {"error": "slow"})
    assert isinstance(e, QuotaError)
    assert e.message == "slow"


def test_dispatch_502_is_upstream():
    e = error_from_response(502, {"detail": "bad gateway"})
    assert isinstance(e, UpstreamError)
    assert "bad gateway" in e.message


def test_dispatch_500_is_upstream():
    e = error_from_response(500, "plain text body")
    assert isinstance(e, UpstreamError)
    assert e.message == "plain text body"


def test_dispatch_400_is_badrequest():
    e = error_from_response(400, {"message": "invalid shape"})
    assert isinstance(e, BadRequestError)
    assert e.message == "invalid shape"


def test_dispatch_418_is_badrequest():
    # 4xx that is not 401/403/429
    e = error_from_response(418, {})
    assert isinstance(e, BadRequestError)


def test_dispatch_other_status_is_base():
    e = error_from_response(301, {})
    assert type(e) is OpenFlowError


def test_default_message_includes_status():
    e = error_from_response(500, None)
    assert "500" in e.message


def test_extract_message_from_nested_error_dict():
    assert _extract_message({"error": {"message": "nested"}}) == "nested"


def test_extract_message_from_error_string():
    assert _extract_message({"error": "flat"}) == "flat"


def test_extract_message_from_detail():
    assert _extract_message({"detail": "d"}) == "d"


def test_extract_message_from_error_description():
    assert _extract_message({"error_description": "oauth style"}) == "oauth style"


def test_extract_message_from_plain_string():
    assert _extract_message("just text") == "just text"


def test_extract_message_returns_none_for_other():
    assert _extract_message(None) is None
    assert _extract_message(123) is None
    assert _extract_message([1, 2]) is None


def test_extract_message_ignores_non_str_fields():
    assert _extract_message({"message": 42}) is None


def test_errors_carry_body_and_request_id():
    body = {"x": 1}
    e = error_from_response(500, body, request_id="rid")
    assert e.body is body
    assert e.request_id == "rid"
