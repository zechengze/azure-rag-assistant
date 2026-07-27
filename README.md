# Azure RAG Knowledge Assistant

[![CI](https://github.com/<owner>/<repo>/actions/workflows/ci.yml/badge.svg)](https://github.com/<owner>/<repo>/actions/workflows/ci.yml)

企業級知識問答系統,整合 Azure OpenAI、Azure AI Search、Azure Document Intelligence 與 RAG (Retrieval-Augmented Generation) 技術。全程使用 Claude Code 進行 AI 輔助開發,作為 AZ-204 認證備考實作專案。

## 系統架構

```mermaid
flowchart TB
    subgraph Client["瀏覽器"]
        UI[React + TypeScript<br/>Vite + Tailwind]
    end

    subgraph App["Azure App Service (Linux Container)"]
        DRF[Django REST Framework<br/>JWT Auth + Throttle + CORS]
        subgraph Services["services/ 層"]
            S_OAI[openai_service.py]
            S_SCH[search_service.py]
            S_BLOB[blob_service.py]
            S_DI[document_intelligence_service.py]
        end
        DB[(PostgreSQL<br/>Document metadata)]
    end

    subgraph Azure["Azure Cognitive & Storage"]
        AOAI[Azure OpenAI<br/>gpt-4.1-mini<br/>text-embedding-3-small]
        AIS[Azure AI Search<br/>Hybrid BM25 + Vector]
        BLOB[Azure Blob Storage<br/>SAS Token]
        DI[Azure Document<br/>Intelligence<br/>prebuilt-layout]
        KV[Azure Key Vault<br/>Managed Identity]
    end

    UI -->|HTTPS REST + SSE| DRF
    DRF --> S_OAI
    DRF --> S_SCH
    DRF --> S_BLOB
    DRF --> DB
    S_BLOB --> S_DI
    S_OAI --> AOAI
    S_SCH --> AIS
    S_SCH --> AOAI
    S_BLOB --> BLOB
    S_DI --> DI
    App -.Managed Identity.-> KV
```

### RAG 資料流

```mermaid
sequenceDiagram
    participant U as User
    participant V as ChatCompletionView
    participant SE as Search Service
    participant AS as Azure AI Search
    participant OA as OpenAI Service
    participant AO as Azure OpenAI

    U->>V: POST /api/chat/ {query, stream:true}
    V->>V: Serializer 驗證 (2000 char + injection 偵測)
    V->>SE: hybrid_search(query, user_id)
    SE->>OA: get_embedding(query)
    OA->>AO: embeddings.create
    AO-->>OA: vector[1536]
    OA-->>SE: vector
    SE->>AS: search(text + vector + filter:user_id)
    AS-->>SE: Top-5 chunks
    SE-->>V: context_documents
    V->>OA: chat_completion_stream(query, context)
    Note over OA,AO: System prompt 注入 context<br/>User message 只放 query
    OA->>AO: chat.completions.create(stream=True)
    AO-->>OA: tokens
    OA-->>V: token iterator
    V-->>U: SSE data: <token>
    V-->>U: SSE data: [DONE]
```

## 功能特色

- **RAG 知識問答**:上傳 PDF/TXT/DOCX 文件,AI 根據文件內容回答問題
- **混合搜尋**:結合關鍵字 (BM25) 與語意向量,提升召回精準度
- **串流回應**:Server-Sent Events 實現打字機效果
- **多租戶隔離**:Azure AI Search 以 `user_id` 過濾,使用者只能搜到自己的文件
- **PDF 表格抽取**:Document Intelligence `prebuilt-layout` 保留表格結構為 Markdown
- **Prompt Injection 防護**:System Prompt 與使用者輸入嚴格分離,召回文件只注入 System

## AZ-204 對應技術點

| 考試範圍 | 本專案實作 |
|---|---|
| Azure App Service | Django 後端容器化部署 (Linux Container) |
| Azure Blob Storage | 文件儲存、SAS Token 存取控制、路徑前綴隔離 |
| Azure OpenAI Service | Chat Completion、Embedding (dev: gpt-4.1-mini / text-embedding-3-small) |
| Azure AI Search | 向量索引、混合搜尋 (BM25 + Vector)、HNSW 演算法 |
| Azure Document Intelligence | PDF 文字 + 表格抽取為 Markdown |
| Azure Key Vault | 機密管理、Managed Identity |
| Microsoft Identity Platform | MSAL、JWT (`djangorestframework-simplejwt`)、Azure AD |
| Azure Monitor | Application Insights、結構化日誌 (stdout) |
| Container Registry | `docker push` 至 ACR,App Service 拉取部署 |

## 開發規範

本專案使用 Claude Code 進行 AI 輔助開發。所有安全規範、程式碼品質標準與協作準則詳見 [CLAUDE.md](./CLAUDE.md)。

## 快速開始

### 前置需求

- Python 3.11+
- Node.js 20+
- Docker / Docker Compose (推薦)
- Azure 訂閱 (AZ-204 沙盒或個人訂閱)
- Azure CLI (部署時需要)

### 方法 A:Docker Compose (推薦,免裝 Python/Postgres)

```bash
cp backend/.env.example backend/.env
# 編輯 backend/.env,填入 Azure 服務連線資訊

docker compose up -d --build
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py createsuperuser

# 後端 http://localhost:8000
# 前端另開 terminal:
cd frontend && npm install && npm run dev   # http://localhost:5173
```

### 方法 B:本地裸機

**後端**

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # 編輯 Azure 連線資訊
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

**前端**

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

### 環境變數參考

完整變數列表見 `backend/.env.example`。核心變數:

```env
# Django
SECRET_KEY=<django-secret-key>
DEBUG=False
ALLOWED_HOSTS=localhost,127.0.0.1
DATABASE_URL=postgresql://raguser:ragpassword@localhost:5432/ragdb
CORS_ALLOWED_ORIGINS=http://localhost:5173

# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/
AZURE_OPENAI_KEY=<your-key>
AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-4.1-mini
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-small
AZURE_OPENAI_API_VERSION=2024-10-21

# Azure AI Search
AZURE_SEARCH_ENDPOINT=https://<resource>.search.windows.net
AZURE_SEARCH_KEY=<your-key>
AZURE_SEARCH_INDEX_NAME=knowledge-base

# Azure Blob Storage
AZURE_STORAGE_CONNECTION_STRING=<your-connection-string>
AZURE_STORAGE_CONTAINER=documents
AZURE_STORAGE_SAS_EXPIRY_HOURS=1

# Azure Document Intelligence
AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=https://<resource>.cognitiveservices.azure.com/
AZURE_DOCUMENT_INTELLIGENCE_KEY=<your-key>
```

## 測試

```bash
# 本機 (需先安裝後端依賴)
cd backend && pytest --cov=. --cov-report=term-missing --cov-fail-under=70

# Docker (隔離環境,推薦)
docker compose run --rm backend pytest --cov=. --cov-fail-under=70
```

所有 Azure SDK 呼叫在測試中均透過 `unittest.mock` 隔離,**禁止呼叫付費 API**。

## API 端點

| 方法 | 路徑 | 描述 |
|---|---|---|
| POST | `/api/token/` | 取得 JWT access + refresh |
| POST | `/api/token/refresh/` | 用 refresh 換新的 access |
| POST | `/api/chat/` | RAG 問答 (支援 `stream=true` SSE 串流) |
| POST | `/api/documents/upload/` | 上傳文件 (multipart, PDF/TXT/DOCX, ≤10MB) |
| DELETE | `/api/documents/<document_id>/` | 軟刪除文件 (Blob + Search index) |

## 部署 (Azure App Service)

```bash
# 1. 建置並推送至 Azure Container Registry
az acr login --name <registry>
docker build -t <registry>.azurecr.io/azure-rag-assistant:latest ./backend
docker push <registry>.azurecr.io/azure-rag-assistant:latest

# 2. 建立 App Service (首次)
az webapp create \
  --resource-group rg-rag-assistant \
  --plan asp-rag-assistant \
  --name azure-rag-assistant \
  --deployment-container-image-name <registry>.azurecr.io/azure-rag-assistant:latest

# 3. 設定 App Setting (環境變數)
az webapp config appsettings set \
  --resource-group rg-rag-assistant \
  --name azure-rag-assistant \
  --settings \
    SECRET_KEY="@Microsoft.KeyVault(SecretUri=...)" \
    AZURE_OPENAI_KEY="@Microsoft.KeyVault(SecretUri=...)" \
    DEBUG=False \
    ALLOWED_HOSTS=azure-rag-assistant.azurewebsites.net
```

生產環境應啟用 Managed Identity 並從 Key Vault 動態解析機密,避免明文儲存。

## 授權

MIT License
