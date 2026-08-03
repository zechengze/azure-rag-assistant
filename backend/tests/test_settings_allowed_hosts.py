"""
ALLOWED_HOSTS 的健康檢查探針例外測試。

探針不經公開網域存取，Host 標頭因此不在白名單內。少了這些項目，
Dockerfile 的 HEALTHCHECK 與 App Service 的平台探針都會拿到
400 DisallowedHost —— 前者永遠不會通過，後者每次探測污染一筆
ERROR 日誌。此行為只在部署後才看得出來，故以測試釘住。
"""

from __future__ import annotations

import socket

from django.conf import settings


class TestAllowedHostsProbeExemptions:
    def test_loopback_hosts_present(self) -> None:
        """Dockerfile 的 HEALTHCHECK 以 localhost:8000 存取。"""
        assert "localhost" in settings.ALLOWED_HOSTS
        assert "127.0.0.1" in settings.ALLOWED_HOSTS

    def test_container_own_address_present(self) -> None:
        """App Service 平台探針以容器私有 IP 存取（如 169.254.130.3）。"""
        own_ip = socket.gethostbyname(socket.gethostname())
        assert own_ip in settings.ALLOWED_HOSTS

    def test_no_wildcard(self) -> None:
        """探針例外不得放寬成萬用字元 —— 見 CLAUDE.md 1.4。"""
        assert "*" not in settings.ALLOWED_HOSTS

    def test_probe_hosts_not_duplicated(self) -> None:
        """
        本機環境下容器位址解析即為 127.0.0.1，已存在者不應重複附加。

        只檢查探針項目：Django 的 setup_test_environment() 會自行附加
        一次 testserver，那不在本模組的職責範圍內。
        """
        own_ip = socket.gethostbyname(socket.gethostname())
        for host in ("localhost", "127.0.0.1", own_ip):
            assert settings.ALLOWED_HOSTS.count(host) == 1, f"{host} 重複出現"
