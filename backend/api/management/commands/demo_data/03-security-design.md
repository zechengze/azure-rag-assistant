# 安全設計決策

## 機密管理與解析順序

所有金鑰、連線字串、密碼一律透過環境變數注入，絕不寫入程式碼或版本控制。專案區分「機密」與「非機密」設定：機密值透過 `core/secrets.py` 的 `get_secret()` 取得，非機密設定（端點 URL、部署名稱）維持以 `config()` 直接讀取環境變數。

`get_secret()` 的解析順序是 Azure Key Vault 優先，環境變數其次。設定了 `AZURE_KEY_VAULT_URL` 才啟用 Key Vault，未設定則完全不建立連線，本機開發與 CI 因此維持單純的 `.env` 流程，不需要 Azure 認證就能跑測試。

認證使用 `DefaultAzureCredential`：生產環境走 App Service 的 Managed Identity，本機開發走 `az login` 的使用者憑證。這個做法的價值在於程式碼中不存在任何用來取得其他機密的機密，也就沒有「第一把鑰匙要放哪裡」的問題。

Key Vault 依交易次數計費，因此只有五個真正的機密走這條路徑，且解析結果在行程內快取。Key Vault 不可用時記錄 warning 並回退環境變數，不中斷應用程式啟動；日誌絕不輸出機密值本身。Secret 名稱需要轉換，因為 Key Vault 不接受底線：`AZURE_OPENAI_KEY` 對應到 `azure-openai-key`。

## Prompt Injection 防護

系統提示詞與使用者輸入嚴格分離。召回的文件段落只注入 System Prompt，絕不放進 User Message。這個界線很重要：如果把檢索到的文件內容放進 user 角色的訊息，被上傳的惡意文件就能偽裝成使用者指令，讓模型忽略原本的系統指示。

Serializer 層另外做輸入長度限制與惡意內容偵測。這是縱深防禦，不是唯一防線——真正的結構性保護來自角色分離。

## 驗證與授權

API 端點使用 JWT 驗證，由 `djangorestframework-simplejwt` 提供。Access token 有效期 60 分鐘，refresh token 7 天並啟用輪替。每個端點都明確標註 `permission_classes`，不依賴全域預設值，因為預設值被改動時，沒有明確標註的端點會靜默地改變授權行為。

健康檢查端點是唯一的例外，明確設定 `permission_classes = [AllowAny]`、清空 `authentication_classes` 與 `throttle_classes`。

## 限流

限流分三個層級：匿名請求每小時 20 次、已驗證使用者每小時 100 次、聊天端點另設每小時 30 次。聊天端點需要獨立且更嚴格的額度，因為它是唯一會觸發付費 AI 推論的端點，其成本結構與其他端點完全不同。

## 資料保護

使用者上傳的檔案存放於 Azure Blob Storage，不落地於應用程式伺服器。存取透過 SAS Token 授權，有效期上限一小時。短效期讓洩漏的 URL 迅速失效，且不需要撤銷機制。

## HTTP 安全標頭

生產環境（`DEBUG=False`）啟用 HSTS（一年、含子網域）、強制 HTTPS 轉向、Secure cookie、`X-Frame-Options: DENY` 與 `X-Content-Type-Options: nosniff`。這些設定綁在 `DEBUG` 判斷式內，因為本機開發沒有 TLS，強制轉向會讓開發環境完全無法使用。

`ALLOWED_HOSTS` 與 CORS 白名單在生產環境都明確列舉，禁用萬用字元。

## 資料庫存取

所有資料庫操作透過 Django ORM，禁止原始 SQL 字串拼接。這在 RAG 系統中尤其重要，因為使用者輸入會流經多個處理階段，任何一處拼接字串都是注入點。
