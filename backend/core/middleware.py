"""Request logging middleware — 結構化記錄每筆請求的方法、路徑、狀態與耗時。"""

from __future__ import annotations

import logging
import time
from typing import Callable

from django.http import HttpRequest, HttpResponse

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        start = time.monotonic()
        response = self.get_response(request)
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info(
            "method=%s path=%s status=%d elapsed_ms=%.2f",
            request.method,
            request.path,
            response.status_code,
            elapsed_ms,
        )
        return response
