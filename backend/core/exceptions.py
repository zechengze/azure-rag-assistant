"""
自訂 DRF 例外處理器,將所有 API 錯誤回應正規化為一致的 JSON 結構。
"""

from __future__ import annotations

import logging
from typing import Any

from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)


def custom_exception_handler(
    exc: Exception, context: dict[str, Any]
) -> Response | None:
    """
    將 DRF 預設例外回應包裝為 {"error": ..., "detail": ...} 結構,
    並對非 DRF 例外記錄完整堆疊。
    """
    response = exception_handler(exc, context)

    if response is None:
        logger.exception("未處理的例外: %s", exc)
        return None

    view = context.get("view")
    request = context.get("request")
    logger.warning(
        "API 例外 | view=%s | path=%s | status=%d | exc=%s",
        view.__class__.__name__ if view else "?",
        request.path if request else "?",
        response.status_code,
        exc,
    )

    response.data = {
        "error": exc.__class__.__name__,
        "detail": response.data,
    }
    return response
