"""
健康檢查探針的 Host 與 SSL 轉向例外測試。

App Service 的啟動探針直接以容器私有位址 (169.254.130.x，每次重啟可能
不同) 存取，Dockerfile 的 HEALTHCHECK 則打 localhost。兩者的 Host 標頭
都不在白名單內，且不帶 X-Forwarded-Proto。少了這些例外，探針會拿到
400 DisallowedHost 或 301 轉向 —— 前者每次啟動污染一筆 ERROR 日誌，
後者讓健康檢查形同虛設。此行為只在部署後才看得出來，故以測試釘住。
"""

from __future__ import annotations

from django.conf import settings
from django.test import Client

from core.middleware import HEALTH_PATH


class TestHealthProbeHostExemption:
    def test_localhost_allowed(self) -> None:
        """middleware 會把探針的 Host 改寫為 localhost，白名單須接受。"""
        assert "localhost" in settings.ALLOWED_HOSTS

    def test_no_wildcard(self) -> None:
        """探針例外不得放寬成萬用字元 —— 見 CLAUDE.md 1.4。"""
        assert "*" not in settings.ALLOWED_HOSTS

    def test_middleware_runs_first(self) -> None:
        """
        排序即正確性：SecurityMiddleware 與 CommonMiddleware 都會呼叫
        request.get_host()，一旦先執行就已經拋出 DisallowedHost。
        """
        assert settings.MIDDLEWARE[0] == "core.middleware.HealthCheckProbeMiddleware"

    def test_health_reachable_with_probe_host(self) -> None:
        """以容器私有位址當 Host 存取健康檢查，應得 200 而非 400。"""
        client = Client()
        response = client.get(HEALTH_PATH, HTTP_HOST="169.254.130.3:8000")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_warmup_path_not_rejected_by_host_check(self) -> None:
        """
        App Service 的暖機探針打 /robots933456.txt。應用程式沒有這條
        路由，回 404 是正確的 —— 重點是不能因為 Host 而變成 400。
        """
        client = Client()
        response = client.get("/robots933456.txt", HTTP_HOST="169.254.130.3:8000")
        assert response.status_code == 404

    def test_other_paths_still_reject_unknown_host(self) -> None:
        """例外僅限探針路徑；其餘路徑的白名單驗證不得被削弱。"""
        client = Client()
        response = client.get("/api/documents/", HTTP_HOST="169.254.130.3:8000")
        assert response.status_code == 400
