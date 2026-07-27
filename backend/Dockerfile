# Azure RAG Knowledge Assistant — 後端 Docker 映像
# 部署目標:Azure App Service (Linux Container)
# Build context:`backend/` 目錄
#   docker build -t azure-rag-assistant ./backend

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 系統相依套件 (psycopg2 編譯需求)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# 先複製 requirements 以利用 Docker layer cache
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# 應用程式碼
COPY . .

# 預先收集靜態檔案 (build time 用 placeholder 環境變數讓 settings 順利載入)
RUN SECRET_KEY=build-time-placeholder \
    AZURE_OPENAI_ENDPOINT=https://placeholder \
    AZURE_OPENAI_KEY=placeholder \
    AZURE_SEARCH_ENDPOINT=https://placeholder \
    AZURE_SEARCH_KEY=placeholder \
    AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=https;AccountName=p;AccountKey=cA==;EndpointSuffix=core.windows.net" \
    python manage.py collectstatic --noinput

# 非 root 使用者 (安全最佳實踐)
RUN useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app
USER appuser

# Azure App Service 預設使用 port 8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/health/ || exit 1

# Gunicorn 作為 WSGI 伺服器
CMD ["gunicorn", "core.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "4", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
