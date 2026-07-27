"""
Pytest 設定 — 必須在 Django 載入 settings 前注入測試用環境變數。
此模組於 conftest 載入時(pytest 啟動初期)執行,故所有 os.environ.setdefault
須以模組層級執行,而非置於 fixture 內。
"""

import os

# Django settings 模組必須能順利匯入 (settings.py 直接 config() 讀取必要變數)
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("DEBUG", "True")
os.environ.setdefault("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:5173")

# Azure 服務的環境變數 — 測試時不會真正呼叫,僅供 settings 模組讀取
os.environ.setdefault("AZURE_OPENAI_ENDPOINT", "https://test.openai.azure.com/")
os.environ.setdefault("AZURE_OPENAI_KEY", "test-openai-key")
os.environ.setdefault("AZURE_SEARCH_ENDPOINT", "https://test.search.windows.net")
os.environ.setdefault("AZURE_SEARCH_KEY", "test-search-key")
os.environ.setdefault(
    "AZURE_STORAGE_CONNECTION_STRING",
    "DefaultEndpointsProtocol=https;AccountName=test;"
    "AccountKey=dGVzdGtleWZvcnVuaXR0ZXN0c29ubHk=;EndpointSuffix=core.windows.net",
)
os.environ.setdefault(
    "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT",
    "https://test.cognitiveservices.azure.com/",
)
os.environ.setdefault("AZURE_DOCUMENT_INTELLIGENCE_KEY", "test-di-key")
