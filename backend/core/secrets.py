"""
機密設定解析層 — 優先從 Azure Key Vault 取得，取不到則回退至環境變數 / .env。

設計原則：
    - 僅「真正的機密」走此模組（API 金鑰、連線字串、Django SECRET_KEY），
      端點 URL、部署名稱等非機密設定仍直接使用 decouple 的 config()。
      Key Vault 依交易次數計費，減少查詢項目即減少成本與啟動延遲。
    - 未設定 AZURE_KEY_VAULT_URL 時完全不建立 Azure 用戶端，
      本機開發與 CI 維持純 .env 流程，無需 Azure 認證。
    - 使用 DefaultAzureCredential：生產環境走 App Service 的 Managed Identity，
      本機開發則自動採用 `az login` 的開發者認證。
    - 任何情況下都不記錄機密值本身，僅記錄設定名稱。

使用情境：
    from core.secrets import get_secret
    AZURE_OPENAI_KEY = get_secret("AZURE_OPENAI_KEY")
"""

from __future__ import annotations

import logging
from typing import Any

from decouple import config

logger = logging.getLogger(__name__)

# 區分「未提供 default」與「default=None」
_UNSET: Any = object()


def to_vault_name(env_name: str) -> str:
    """
    將環境變數名稱轉換為合法的 Key Vault secret 名稱。

    Key Vault 僅允許英數字與連字號，故底線一律轉為連字號並轉小寫。

    Args:
        env_name: 環境變數名稱，例如 "AZURE_OPENAI_KEY"

    Returns:
        對應的 secret 名稱，例如 "azure-openai-key"
    """
    return env_name.lower().replace("_", "-")


def _is_missing_secret(exc: Exception) -> bool:
    """
    判斷例外是否為「此 secret 不存在」，而非 Key Vault 整體不可用。

    僅有前者可安全地繼續查詢其餘 secret；連線逾時、DNS 解析失敗、
    認證錯誤等屬於後者，會在每個 secret 上重複發生。
    """
    try:
        from azure.core.exceptions import ResourceNotFoundError
    except ImportError:  # pragma: no cover - azure SDK 必為安裝相依
        return False
    return isinstance(exc, ResourceNotFoundError)


class KeyVaultResolver:
    """
    延遲初始化的 Key Vault 讀取器，附帶行程內快取。

    Key Vault 不可用（未設定 URL、認證失敗、網路異常）時會停用自身，
    後續查詢直接回傳 None 讓呼叫端回退至環境變數，不會反覆重試。
    """

    def __init__(self, vault_url: str | None = None) -> None:
        self._vault_url = (
            vault_url
            if vault_url is not None
            else config("AZURE_KEY_VAULT_URL", default="")
        )
        self._client: Any = None
        self._cache: dict[str, str] = {}
        self._disabled = not self._vault_url

    @property
    def enabled(self) -> bool:
        """Key Vault 是否仍可用（未設定或初始化失敗即為 False）。"""
        return not self._disabled

    def _get_client(self) -> Any:
        """建立（或取用既有的）SecretClient，失敗則停用本解析器。"""
        if self._client is not None:
            return self._client
        try:
            from azure.identity import DefaultAzureCredential
            from azure.keyvault.secrets import SecretClient

            self._client = SecretClient(
                vault_url=self._vault_url,
                credential=DefaultAzureCredential(),
            )
            logger.info("Key Vault 已啟用: %s", self._vault_url)
        except Exception as exc:
            logger.warning("Key Vault 初始化失敗，改用環境變數: %s", exc, exc_info=True)
            self._disabled = True
        return self._client

    def get(self, env_name: str) -> str | None:
        """
        讀取單一機密，取不到時回傳 None（由呼叫端決定回退行為）。

        Args:
            env_name: 環境變數名稱，內部會轉換為 Key Vault secret 名稱

        Returns:
            機密值；Key Vault 停用、查無此 secret 或讀取失敗時為 None
        """
        if self._disabled:
            return None
        if env_name in self._cache:
            return self._cache[env_name]

        client = self._get_client()
        if client is None:
            return None

        secret_name = to_vault_name(env_name)
        try:
            value = client.get_secret(secret_name).value
        except Exception as exc:
            # 單一 secret 缺漏屬正常情境（僅部分機密託管於 Key Vault），
            # 記錄後回退環境變數即可，不影響其他 secret 的讀取。
            if _is_missing_secret(exc):
                logger.warning("Key Vault 查無 %s，改用環境變數", secret_name)
                return None
            # 連線或認證層級的失敗會重複發生於每個 secret，
            # 且 SDK 本身帶重試 — 直接停用解析器，避免啟動時間倍增。
            logger.warning(
                "Key Vault 無法存取（%s），本次啟動改用環境變數: %s",
                secret_name,
                exc,
            )
            self._disabled = True
            return None

        if value is None:
            return None
        self._cache[env_name] = value
        return value


# 模組層級單例 — Django settings 匯入時建立，整個行程共用同一份快取
_resolver = KeyVaultResolver()


def get_secret(name: str, default: Any = _UNSET) -> Any:
    """
    解析機密設定：Key Vault 優先，其次為環境變數 / .env。

    Args:
        name: 環境變數名稱，例如 "AZURE_SEARCH_KEY"
        default: 兩處皆無值時的預設值；未提供時將由 decouple 拋出
            UndefinedValueError，讓設定缺漏在啟動階段即失敗

    Returns:
        機密值

    Raises:
        UndefinedValueError: 未提供 default 且兩處皆查無此設定
    """
    value = _resolver.get(name)
    if value is not None:
        return value
    if default is _UNSET:
        return config(name)
    return config(name, default=default)
