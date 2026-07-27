"""
core.secrets 測試 — Key Vault 解析與環境變數回退行為。
所有 Azure SDK 呼叫皆以 mock 替換，測試中不會建立真實 Key Vault 連線。
"""

from unittest.mock import MagicMock, patch

import pytest
from azure.core.exceptions import ResourceNotFoundError, ServiceRequestError
from decouple import UndefinedValueError

from core.secrets import KeyVaultResolver, get_secret, to_vault_name

VAULT_URL = "https://kv-test.vault.azure.net/"


def _resolver_with_client(client: MagicMock) -> KeyVaultResolver:
    """建立已注入 mock 用戶端的 resolver，跳過真實 SDK 初始化。"""
    resolver = KeyVaultResolver(vault_url=VAULT_URL)
    resolver._client = client
    return resolver


class TestToVaultName:
    def test_underscores_become_dashes_and_lowercase(self) -> None:
        assert to_vault_name("AZURE_OPENAI_KEY") == "azure-openai-key"

    def test_already_valid_name_unchanged(self) -> None:
        assert to_vault_name("secretkey") == "secretkey"


class TestKeyVaultResolver:
    def test_disabled_without_vault_url(self) -> None:
        resolver = KeyVaultResolver(vault_url="")
        assert resolver.enabled is False
        assert resolver.get("AZURE_OPENAI_KEY") is None

    def test_returns_secret_value(self) -> None:
        client = MagicMock()
        client.get_secret.return_value.value = "vault-value"
        resolver = _resolver_with_client(client)

        assert resolver.get("AZURE_OPENAI_KEY") == "vault-value"
        client.get_secret.assert_called_once_with("azure-openai-key")

    def test_second_read_is_cached(self) -> None:
        client = MagicMock()
        client.get_secret.return_value.value = "vault-value"
        resolver = _resolver_with_client(client)

        resolver.get("AZURE_SEARCH_KEY")
        resolver.get("AZURE_SEARCH_KEY")

        # 快取命中 — 避免重複的 Key Vault 計費交易
        assert client.get_secret.call_count == 1

    def test_missing_secret_returns_none_without_disabling(self) -> None:
        client = MagicMock()
        client.get_secret.side_effect = [
            ResourceNotFoundError("SecretNotFound"),
            MagicMock(value="second-value"),
        ]
        resolver = _resolver_with_client(client)

        assert resolver.get("AZURE_OPENAI_KEY") is None
        # 單一 secret 缺漏不應中斷其餘查詢
        assert resolver.enabled is True
        assert resolver.get("AZURE_SEARCH_KEY") == "second-value"

    def test_unreachable_vault_disables_resolver(self) -> None:
        client = MagicMock()
        client.get_secret.side_effect = ServiceRequestError("DNS failure")
        resolver = _resolver_with_client(client)

        assert resolver.get("AZURE_OPENAI_KEY") is None
        # 連線層級失敗會重複發生 — 後續 secret 不應再次嘗試
        assert resolver.enabled is False
        assert resolver.get("AZURE_SEARCH_KEY") is None
        assert client.get_secret.call_count == 1

    def test_none_valued_secret_is_not_cached(self) -> None:
        client = MagicMock()
        client.get_secret.return_value.value = None
        resolver = _resolver_with_client(client)

        assert resolver.get("AZURE_OPENAI_KEY") is None
        assert "AZURE_OPENAI_KEY" not in resolver._cache

    def test_client_init_failure_disables_resolver(self) -> None:
        resolver = KeyVaultResolver(vault_url=VAULT_URL)
        with patch(
            "azure.keyvault.secrets.SecretClient",
            side_effect=Exception("no credential"),
        ):
            assert resolver.get("AZURE_OPENAI_KEY") is None
        assert resolver.enabled is False

    def test_client_is_reused_across_calls(self) -> None:
        resolver = KeyVaultResolver(vault_url=VAULT_URL)
        client = MagicMock()
        client.get_secret.return_value.value = "v"
        with (
            patch(
                "azure.keyvault.secrets.SecretClient", return_value=client
            ) as mock_cls,
            patch("azure.identity.DefaultAzureCredential"),
        ):
            resolver.get("AZURE_OPENAI_KEY")
            resolver.get("AZURE_SEARCH_KEY")

        assert mock_cls.call_count == 1


class TestGetSecret:
    def test_prefers_vault_over_environment(self, monkeypatch) -> None:
        monkeypatch.setenv("AZURE_OPENAI_KEY", "env-value")
        with patch("core.secrets._resolver.get", return_value="vault-value"):
            assert get_secret("AZURE_OPENAI_KEY") == "vault-value"

    def test_falls_back_to_environment(self, monkeypatch) -> None:
        monkeypatch.setenv("AZURE_OPENAI_KEY", "env-value")
        with patch("core.secrets._resolver.get", return_value=None):
            assert get_secret("AZURE_OPENAI_KEY") == "env-value"

    def test_uses_default_when_missing_everywhere(self) -> None:
        with patch("core.secrets._resolver.get", return_value=None):
            assert get_secret("NO_SUCH_SETTING_ANYWHERE", default="") == ""

    def test_raises_when_required_setting_missing(self) -> None:
        # 缺漏的必要設定應在啟動階段就失敗，而非執行期才報錯
        with patch("core.secrets._resolver.get", return_value=None):
            with pytest.raises(UndefinedValueError):
                get_secret("NO_SUCH_SETTING_ANYWHERE")
