"""
Django settings for Azure RAG Knowledge Assistant.
使用 python-decouple 管理環境變數，所有機密資訊透過 .env 或 Azure Key Vault 注入。
"""

from datetime import timedelta
from pathlib import Path

import dj_database_url
from decouple import Csv, config

from core.secrets import get_secret

BASE_DIR = Path(__file__).resolve().parent.parent

# Security — 生產環境絕不開啟 DEBUG
# 機密值一律走 get_secret()：設定 AZURE_KEY_VAULT_URL 時改由 Key Vault 供應，
# 未設定則沿用 .env（本機開發與 CI）。非機密設定維持 config()。
SECRET_KEY = get_secret("SECRET_KEY")
DEBUG = config("DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", cast=Csv(), default="localhost,127.0.0.1")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "django_filters",
    "api.apps.ApiConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    # SessionMiddleware 必須在 AuthenticationMiddleware 與 MessageMiddleware 之前
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.RequestLoggingMiddleware",
]

ROOT_URLCONF = "core.urls"
WSGI_APPLICATION = "core.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": dj_database_url.config(
        default=config("DATABASE_URL", default="sqlite:///db.sqlite3")
    )
}

# Django REST Framework
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    # 額度可由環境變數覆寫：公開 demo 由多位訪客共用單一帳號，
    # 需要比一般部署更嚴格的上限來封住 AI 推論成本。
    "DEFAULT_THROTTLE_RATES": {
        "anon": config("THROTTLE_ANON", default="20/hour"),
        "user": config("THROTTLE_USER", default="100/hour"),
        "chat": config("THROTTLE_CHAT", default="30/hour"),
    },
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.OrderingFilter",
    ],
    "EXCEPTION_HANDLER": "core.exceptions.custom_exception_handler",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
}

# CORS — 生產環境明確列出允許來源
CORS_ALLOWED_ORIGINS = config(
    "CORS_ALLOWED_ORIGINS",
    cast=Csv(),
    default="http://localhost:5173,http://localhost:3000",
)
CORS_ALLOW_CREDENTIALS = True

# JWT 設定
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    # 若需 blacklist 舊 refresh token,須加入 INSTALLED_APPS:
    #   "rest_framework_simplejwt.token_blacklist"
    # 並執行 migrate。MVP 階段先關閉以簡化部署。
    "BLACKLIST_AFTER_ROTATION": False,
}

# HTTP 安全標頭 (生產環境)
if not DEBUG:
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    X_FRAME_OPTIONS = "DENY"
    SECURE_CONTENT_TYPE_NOSNIFF = True

# Azure OpenAI
AZURE_OPENAI_ENDPOINT = config("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_KEY = get_secret("AZURE_OPENAI_KEY")
AZURE_OPENAI_CHAT_DEPLOYMENT = config(
    "AZURE_OPENAI_CHAT_DEPLOYMENT", default="gpt-4.1-mini"
)
AZURE_OPENAI_EMBEDDING_DEPLOYMENT = config(
    "AZURE_OPENAI_EMBEDDING_DEPLOYMENT", default="text-embedding-3-small"
)
AZURE_OPENAI_API_VERSION = config("AZURE_OPENAI_API_VERSION", default="2024-10-21")

# Azure AI Search
AZURE_SEARCH_ENDPOINT = config("AZURE_SEARCH_ENDPOINT")
AZURE_SEARCH_KEY = get_secret("AZURE_SEARCH_KEY")
AZURE_SEARCH_INDEX_NAME = config("AZURE_SEARCH_INDEX_NAME", default="knowledge-base")

# Azure Blob Storage
AZURE_STORAGE_CONNECTION_STRING = get_secret("AZURE_STORAGE_CONNECTION_STRING")
AZURE_STORAGE_CONTAINER = config("AZURE_STORAGE_CONTAINER", default="documents")
AZURE_STORAGE_SAS_EXPIRY_HOURS = config(
    "AZURE_STORAGE_SAS_EXPIRY_HOURS", default=1, cast=int
)

# Azure Document Intelligence
AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT = config(
    "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", default=""
)
AZURE_DOCUMENT_INTELLIGENCE_KEY = get_secret(
    "AZURE_DOCUMENT_INTELLIGENCE_KEY", default=""
)

# RAG 參數
RAG_CHUNK_SIZE = 512  # tokens per chunk
RAG_CHUNK_OVERLAP = 128  # overlap tokens
RAG_TOP_K = 5  # 召回文件數量
RAG_MAX_QUERY_LENGTH = 2000  # 查詢字元上限

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "zh-hant"
TIME_ZONE = "Asia/Taipei"
USE_TZ = True

# Logging — 結構化輸出至 stdout (容器友善)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": config("DJANGO_LOG_LEVEL", default="INFO"),
            "propagate": False,
        },
        "api": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "services": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "core": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
