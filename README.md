# Azure RAG Knowledge Assistant

[![CI](https://github.com/zechengze/azure-rag-assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/zechengze/azure-rag-assistant/actions/workflows/ci.yml)
[![Deploy Backend](https://github.com/zechengze/azure-rag-assistant/actions/workflows/deploy-backend.yml/badge.svg)](https://github.com/zechengze/azure-rag-assistant/actions/workflows/deploy-backend.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)

企業級知識問答系統,整合 Azure OpenAI、Azure AI Search、Azure Document Intelligence 與 RAG (Retrieval-Augmented Generation) 技術。全程使用 Claude Code 進行 AI 輔助開發,作為 AZ-204 認證備考實作專案。

## 線上 Demo

**https://proud-sea-027c74800.7.azurestaticapps.net**

| 帳號 | 密碼 |
|---|---|
| `demo` | `RagDemo2026` |

> 這是公開的展示帳號,密碼刻意公開。可自由上傳文件試用,亦已設定限流與費用上限。

登入後知識庫已預先索引三份說明本系統架構的文件,可以直接提問,例如:

- 「這個系統怎麼做多租戶隔離?」
- 「為什麼要用混合搜尋而不是純向量搜尋?」
- 「chunk 大小和重疊是多少,為什麼這樣設?」
- 「Prompt injection 是怎麼防的?」

也可以自行上傳 PDF / TXT / DOCX(≤10MB)測試。

> Demo 環境為 Free / B1 等級並設有限流(聊天 15 次/小時),僅供功能展示。
> 部署方式與成本明細見 [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md)。

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
    V-->>U: SSE data: {"token": "..."}
    V-->>U: SSE data: {"done": true}
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

| 方法 | 路徑 | 驗證 | 描述 |
|---|---|---|---|
| GET | `/api/health/` | — | 健康檢查 (不查 DB、不呼叫 Azure) |
| POST | `/api/token/` | — | 取得 JWT access + refresh |
| POST | `/api/token/refresh/` | — | 用 refresh 換新的 access |
| POST | `/api/chat/` | JWT | RAG 問答 (支援 `stream=true` SSE 串流) |
| GET | `/api/documents/` | JWT | 列出目前使用者的文件 |
| POST | `/api/documents/upload/` | JWT | 上傳文件 (multipart, PDF/TXT/DOCX, ≤10MB) |
| DELETE | `/api/documents/<document_id>/` | JWT | 軟刪除文件 (Blob + Search index) |

限流預設值:匿名 20 次/小時、已驗證 100 次/小時、聊天端點 30 次/小時。聊天端點需要獨立且更嚴格的額度,因為它是唯一會觸發付費 AI 推論的端點。三者皆可透過 `THROTTLE_ANON` / `THROTTLE_USER` / `THROTTLE_CHAT` 覆寫。

## 部署

一次性佈建整個 Azure 環境:

```bash
cp infra/provision.env.example infra/provision.env   # 填入設定
./infra/provision.sh
```

腳本會建立 resource group、ACR、Storage、AI Search、Key Vault 與 App Service,為 web app 啟用 Managed Identity 並授予 Key Vault 與 ACR 的最小必要角色,把機密寫入 Key Vault,並註冊 GitHub Actions 用的 OIDC federated credential。腳本是 idempotent 的,失敗修正後可直接重跑。

後續部署全自動:

| Workflow | 觸發 | 動作 |
|---|---|---|
| [ci.yml](.github/workflows/ci.yml) | push / PR to main | black、isort、flake8、mypy、pytest (≥70% 覆蓋率)、前端 tsc + build |
| [deploy-backend.yml](.github/workflows/deploy-backend.yml) | `backend/**` 變更 | build image → ACR → App Service → 輪詢健康檢查 |
| [deploy-frontend.yml](.github/workflows/deploy-frontend.yml) | `frontend/**` 變更 | Vite build → Static Web Apps |

部署認證使用 **OIDC federated credential**:GitHub 為每次 workflow run 簽發短效期 token 換取 Azure access token,儲存庫內因此沒有任何長期有效的密碼。

後端部署會在重啟後輪詢 `/api/health/` 最多 5 分鐘,健康檢查沒通過就算部署失敗——只確認「映像推送成功」會把容器啟動失敗的部署誤判為綠燈。

完整步驟、成本明細($20–25/月)與疑難排解見 **[docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md)**。

### 建立 demo 資料

```bash
DEMO_PASSWORD='<password>' python manage.py seed_demo
```

索引一組說明本系統架構的語料,讓線上 demo 能回答關於自己的問題。指令為 idempotent,且拒絕在未設定 `DEMO_PASSWORD` 時以預設密碼建立公開帳號。

## 工程實踐

本專案全程使用 Claude Code 進行 AI 輔助開發,[CLAUDE.md](./CLAUDE.md) 定義了所有 AI 產出程式碼必須遵循的安全與品質規範。AI 加速了實作,但不放寬驗收標準:

- **格式與靜態分析**:black(88 字元)、isort、flake8、mypy,CI 強制
- **測試**:96 個測試、91% 覆蓋率,CI 以 `--cov-fail-under=70` 設下門檻。所有 Azure SDK 呼叫皆 mock,測試絕不呼叫付費 API
- **型別註解**:所有公開函數與方法標註型別
- **人工複審範圍**:資安邏輯(認證、授權、加密)、資料庫 migration、IaC 與生產環境設定變更一律人工複審後才使用
- **Commit 規範**:Conventional Commits

## 授權

MIT License — 見 [LICENSE](./LICENSE)
