"""
測試專用設定 — 由 pytest.ini 的 DJANGO_SETTINGS_MODULE 指定。

**為什麼不能放在 conftest.py**

pytest-django 會在初始 conftest.py 被匯入「之前」就載入 settings，因此在
conftest.py 裡呼叫 os.environ.setdefault 為時已晚：settings.py 早已透過
python-decouple 從開發者本機的 .env 讀完值。實際後果是本機跑測試時，
settings 裡帶的是真實的 Azure 金鑰與開發用 postgres 連線，測試是否通過
還取決於本機 postgres 有沒有在跑。

改成一個獨立的 settings 模組，就能保證環境變數在 core.settings 被匯入前
就已注入。

**為什麼用賦值而非 setdefault**

一律強制覆寫，讓測試在本機與 CI 得到完全相同的設定，.env 的內容不會滲漏
進測試。CLAUDE.md 要求測試絕不呼叫付費 API——即使某個測試漏掉 mock，
這裡的佔位值也保證它打不到真實服務。
"""

import os

os.environ.update(
    {
        # ── Django ──
        "SECRET_KEY": "test-secret-key-not-for-production",
        # DEBUG 必須為 True:False 會啟用 SECURE_SSL_REDIRECT,
        # 測試用戶端的請求會全部變成 301 轉向。
        "DEBUG": "True",
        "ALLOWED_HOSTS": "localhost,127.0.0.1,testserver",
        "DATABASE_URL": "sqlite:///:memory:",
        "CORS_ALLOWED_ORIGINS": "http://localhost:5173",
        # ── 限流 (固定為預設值,避免 .env 覆寫導致測試結果不穩) ──
        "THROTTLE_ANON": "20/hour",
        "THROTTLE_USER": "100/hour",
        "THROTTLE_CHAT": "30/hour",
        # ── Azure 佔位值 — 全部為假值,SDK 呼叫一律 mock ──
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com/",
        "AZURE_OPENAI_KEY": "test-openai-key",
        "AZURE_OPENAI_CHAT_DEPLOYMENT": "gpt-4.1-mini",
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT": "text-embedding-3-small",
        "AZURE_SEARCH_ENDPOINT": "https://test.search.windows.net",
        "AZURE_SEARCH_KEY": "test-search-key",
        "AZURE_SEARCH_INDEX_NAME": "knowledge-base-test",
        "AZURE_STORAGE_CONNECTION_STRING": (
            "DefaultEndpointsProtocol=https;AccountName=test;"
            "AccountKey=dGVzdGtleWZvcnVuaXR0ZXN0c29ubHk=;"
            "EndpointSuffix=core.windows.net"
        ),
        "AZURE_STORAGE_CONTAINER": "documents-test",
        "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT": (
            "https://test.cognitiveservices.azure.com/"
        ),
        "AZURE_DOCUMENT_INTELLIGENCE_KEY": "test-di-key",
    }
)

# 移除 Key Vault 設定:留著會讓 core.secrets 嘗試以 DefaultAzureCredential
# 建立真實連線,測試因此變慢且依賴本機 az login 狀態。
os.environ.pop("AZURE_KEY_VAULT_URL", None)

from core.settings import *  # noqa: E402,F401,F403  # isort: skip
