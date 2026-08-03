"""共用 middleware — 請求記錄與健康檢查探針的 Host 例外。"""

from __future__ import annotations

import logging
import time
from typing import Callable

from django.http import HttpRequest, HttpResponse

logger = logging.getLogger(__name__)

HEALTH_PATH = "/api/health/"


class HealthCheckProbeMiddleware:
    """
    讓健康檢查端點不受 ALLOWED_HOSTS 限制。

    App Service 的啟動探針直接以容器私有位址存取（觀察到 169.254.130.3
    與 169.254.130.5，位址每次重啟可能不同，因此無法列舉加入白名單）。
    Host 標頭永遠不在白名單內，每次容器啟動都在日誌留下一筆
    DisallowedHost ERROR，且探針拿不到真正的 200。

    僅對健康檢查這一條路徑改寫 Host 標頭。該端點不需驗證、不查 DB、
    不回傳任何資料（見 api.views.HealthView），改寫不會擴大攻擊面；
    其餘路徑的 ALLOWED_HOSTS 驗證完全不受影響。

    必須排在 MIDDLEWARE 最前面 —— SecurityMiddleware 與 CommonMiddleware
    都會呼叫 request.get_host()，一旦執行到就已經拋出 DisallowedHost。
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # request.path 取自 PATH_INFO，與 Host 標頭無關，因此在
        # 主機驗證之前就可以安全判讀。
        if request.path == HEALTH_PATH:
            request.META["HTTP_HOST"] = "localhost"
        return self.get_response(request)


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
