# CLAUDE.md — AI 輔助開發規範

本文件定義此專案使用 Claude Code 進行 AI 輔助開發時，所有程式碼品質、安全規範與協作準則。
所有透過 Claude Code 產生或修改的程式碼，均須符合以下規範。

---

## 專案簡介

**Azure RAG Knowledge Assistant** 是一個整合 Azure OpenAI、Azure AI Search 與 Azure Blob Storage 的全端知識問答應用程式，作為 AZ-204 備考專案，示範企業級 AI 應用的開發實踐。

技術堆疊：Python Django REST Framework / React / Azure OpenAI / Azure AI Search / PostgreSQL

---

## 一、安全規範 (Security)

### 1.1 機密資訊管理

- 所有金鑰、連線字串、密碼一律透過環境變數注入，絕不寫入程式碼或版本控制
- 使用 `python-decouple` 或 `django-environ` 管理環境設定
- `.env` 檔案已列入 `.gitignore`，提供 `.env.example` 作為範本（不含實際值）
- Azure 服務金鑰統一透過 Azure Key Vault 或 Managed Identity 取得

**機密解析順序（`core/secrets.py`）**

機密設定一律呼叫 `get_secret()`，非機密設定（端點 URL、部署名稱）維持 `config()`：

```python
from core.secrets import get_secret

AZURE_OPENAI_KEY = get_secret("AZURE_OPENAI_KEY")      # Key Vault → .env
AZURE_OPENAI_ENDPOINT = config("AZURE_OPENAI_ENDPOINT")  # 非機密，直接讀取
```

- 設定 `AZURE_KEY_VAULT_URL` 時啟用 Key Vault，未設定則完全不連線（本機／CI 維持 .env 流程）
- Secret 名稱轉換：`AZURE_OPENAI_KEY` → `azure-openai-key`（Key Vault 不接受底線）
- 認證使用 `DefaultAzureCredential`：生產走 App Service Managed Identity，本機走 `az login`
- Key Vault 依交易次數計費，故僅 5 個真正的機密走此路徑，且結果於行程內快取
- Key Vault 不可用時記錄 warning 並回退環境變數，不中斷啟動；日誌絕不輸出機密值

```python
# 正確範例
from decouple import config
AZURE_OPENAI_KEY = config("AZURE_OPENAI_KEY")

# 禁止範例
AZURE_OPENAI_KEY = "sk-xxxxxxxxxxxxxxxx"  # 嚴禁硬編碼
```

### 1.2 輸入驗證與防護

- 所有 API 輸入使用 Django REST Framework Serializer 進行驗證
- RAG 查詢輸入須進行長度限制（最大 2000 字元）與惡意內容過濾
- 防範 Prompt Injection：使用者輸入與系統提示詞須分離處理
- 所有資料庫操作使用 ORM，禁止原始 SQL 字串拼接

```python
# 正確範例：使用 ORM
documents = Document.objects.filter(user=request.user, is_active=True)

# 禁止範例：SQL 拼接
query = f"SELECT * FROM documents WHERE user_id = {user_id}"  # 嚴禁
```

### 1.3 驗證與授權

- API 端點使用 JWT Token 驗證（`djangorestframework-simplejwt`）
- Azure AD 整合使用 MSAL（Microsoft Authentication Library）
- 所有需要認證的端點須明確標註 `permission_classes`
- 遵循最小權限原則：Azure 服務主體僅授予必要角色

### 1.4 CORS 與 HTTP 安全標頭

- 生產環境 `ALLOWED_HOSTS` 不得使用萬用字元 `*`
- 設定 `Content-Security-Policy`、`X-Frame-Options`、`X-Content-Type-Options`
- CORS 白名單明確列出允許來源，禁止開放所有來源於生產環境

### 1.5 資料保護

- 使用者上傳文件儲存於 Azure Blob Storage，不存放於應用程式伺服器
- Blob 存取使用 SAS Token，設定合理過期時間（最長 1 小時）
- 敏感欄位（如 API 回應中的個人資訊）在記錄日誌前須遮罩處理

---

## 二、程式碼品質規範 (Code Quality)

### 2.1 Python 後端規範

**格式化與 Lint**
```bash
# 執行程式碼格式化
black .
isort .

# 執行靜態分析
flake8 .
mypy .
```

- 行寬上限：88 字元（black 預設）
- 型別註解：所有公開函數與方法須標註型別（Python 3.10+）
- Docstring：公開 API、Service 類別、複雜邏輯須附說明

**命名慣例**
- 變數與函數：`snake_case`
- 類別：`PascalCase`
- 常數：`UPPER_SNAKE_CASE`
- 私有方法：`_leading_underscore`

### 2.2 TypeScript / React 前端規範

- 使用 TypeScript strict 模式，禁止使用 `any` 型別
- 元件一律使用函數式元件（Function Component）+ Hooks
- 使用 ESLint + Prettier 維持格式一致性
- Props 介面須明確定義，使用 `interface` 而非 `type` for object shapes

### 2.3 Git 提交規範

遵循 Conventional Commits 格式：

```
<type>(<scope>): <description>

[optional body]
[optional footer]
```

允許的 type：
- `feat` — 新功能
- `fix` — 錯誤修正
- `docs` — 文件更新
- `refactor` — 重構（不影響功能）
- `test` — 測試相關
- `chore` — 建置、依賴更新
- `security` — 安全修補

範例：
```
feat(rag): implement document chunking with Azure AI Search indexer
fix(auth): handle expired JWT token refresh edge case
security(api): add rate limiting to chat completion endpoint
```

### 2.4 測試規範

- 單元測試覆蓋率目標：≥ 70%（CI 透過 `pytest --cov-fail-under=70` 強制）
- 使用 `pytest` + `pytest-django` 進行後端測試
- 使用 `pytest-mock` / `unittest.mock` 模擬外部 Azure 服務呼叫（禁止在測試中實際呼叫付費 API）
- 整合測試使用 `django.test.TestCase`，測試資料庫隔離

```python
# 測試範例：模擬 Azure OpenAI 呼叫
@patch("services.openai_service.AzureOpenAI")
def test_chat_completion(mock_openai, client):
    mock_openai.return_value.chat.completions.create.return_value = MockResponse(...)
    response = client.post("/api/chat/", {"query": "test"})
    assert response.status_code == 200
```

---

## 三、架構規範 (Architecture)

### 3.1 Django 應用結構

```
backend/
├── api/           # DRF Views、Serializers、URLs、Models
├── core/          # Django 設定、共用工具、例外處理、Middleware
├── services/      # 業務邏輯層（Azure 服務封裝）
│   ├── openai_service.py                # Azure OpenAI 整合（chat + embedding）
│   ├── search_service.py                # Azure AI Search / RAG 混合搜尋
│   ├── blob_service.py                  # Azure Blob Storage + SAS + MIME 路由文字抽取
│   └── document_intelligence_service.py # Azure Document Intelligence（PDF 文字 + 表格）
└── tests/         # 測試套件
```

**文件抽取路由**：`blob_service.extract_text()` 依 MIME 類型分派：
- `application/pdf` → `document_intelligence_service`（保留表格 Markdown）
- `text/plain` → 直接讀取
- DOCX → `python-docx`

### 3.2 服務層原則

- Azure 服務呼叫統一封裝於 `services/` 層，View 層不直接呼叫 SDK
- 使用依賴注入便於測試替換
- 所有外部 API 呼叫加入重試機制（`tenacity` 或 `azure-core` 內建 retry）
- 錯誤處理：Azure SDK 例外須轉換為應用程式定義的例外型別

### 3.3 RAG 流程規範

```
使用者查詢 → 輸入驗證 → Embedding 生成 → Azure AI Search 向量檢索
→ 文件段落召回 → Prompt 組裝 → Azure OpenAI 生成 → 回應過濾 → 回傳使用者
```

- Chunk 大小：512 tokens，重疊 128 tokens，依句子邊界切分
- 召回文件數量：Top-K = 5（向量過召回 2K，混合搜尋後重排）
- System Prompt 與使用者輸入嚴格分離，召回文件僅注入 System Prompt，禁止注入 User Message
- 開發環境使用 `gpt-4.1-mini` + `text-embedding-3-small`（1536 維）以降低成本，生產可切換至 `gpt-4.1` / `text-embedding-3-large`

---

## 四、Claude Code 使用準則

### 4.1 AI 生成程式碼審查要求

使用 Claude Code 產生程式碼後，開發者須執行以下確認：

- [ ] 確認無硬編碼機密資訊
- [ ] 確認型別註解完整
- [ ] 確認錯誤處理邏輯合理（非單純 `pass` 或空 `except`）
- [ ] 確認測試已同步更新或新增
- [ ] 確認符合本文件所有命名與格式規範

### 4.2 Claude Code 的允許範圍

允許：
- 功能實作、重構、測試產生
- 文件與 Docstring 撰寫
- Azure SDK 使用範例查詢與實作

需人工複審後方可使用：
- 資安相關邏輯（認證、授權、加密）
- 資料庫 Migration
- 基礎架構即程式碼（IaC）
- 生產環境設定變更

### 4.3 CLAUDE.md 維護責任

本文件隨專案演進持續更新，任何影響開發規範的架構決策須同步更新此文件。

---

## 五、開發環境設置

```bash
# 後端環境
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 複製環境變數範本
cp .env.example .env
# 填入實際的 Azure 設定值

# 執行資料庫 Migration
python manage.py migrate

# 啟動開發伺服器
python manage.py runserver

# 執行測試
pytest --cov=. --cov-report=html
```

```bash
# 前端環境
cd frontend
npm install
npm run dev
```

---

## 六、AZ-204 對應技術點

| 考試範圍 | 專案實作 |
|---|---|
| Azure App Service | Django 後端部署至 Azure App Service（Linux Container） |
| Azure Blob Storage | 文件上傳、SAS Token 存取、RAG 語料儲存 |
| Azure OpenAI Service | Chat Completion、Embedding 生成 |
| Azure AI Search | 向量索引建立、混合搜尋（BM25 + Vector） |
| Azure Document Intelligence | PDF 文字與表格抽取（保留結構為 Markdown） |
| Azure Key Vault | 機密管理、Managed Identity |
| Microsoft Identity Platform | Azure AD 驗證、JWT、MSAL 整合 |
| Azure Monitor | 應用程式記錄、效能監控 |

---

*最後更新：2026-05*
*維護者：開發團隊*
*版本：1.0.0*
