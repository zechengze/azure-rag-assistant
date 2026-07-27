"""
core.exceptions.custom_exception_handler 單元測試。
"""

from __future__ import annotations

from unittest.mock import MagicMock

from rest_framework.exceptions import NotFound, ValidationError

from core.exceptions import custom_exception_handler


def test_handler_returns_none_for_non_drf_exceptions():
    context = {"view": MagicMock(), "request": MagicMock(path="/x/")}
    result = custom_exception_handler(RuntimeError("not handled by DRF"), context)
    assert result is None


def test_handler_wraps_drf_exception_in_structured_payload():
    context = {"view": MagicMock(), "request": MagicMock(path="/api/x/")}
    exc = NotFound("資源未找到")
    response = custom_exception_handler(exc, context)
    assert response is not None
    assert response.status_code == 404
    assert response.data["error"] == "NotFound"
    assert "detail" in response.data


def test_handler_includes_validation_errors():
    context = {"view": MagicMock(), "request": MagicMock(path="/api/x/")}
    exc = ValidationError({"query": ["不可空白"]})
    response = custom_exception_handler(exc, context)
    assert response is not None
    assert response.status_code == 400
    assert response.data["error"] == "ValidationError"
