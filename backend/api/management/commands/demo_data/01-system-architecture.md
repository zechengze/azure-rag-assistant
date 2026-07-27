# Azure RAG Knowledge Assistant — 系統架構

## 整體分層

本系統分為三層。前端是 React 18 + TypeScript，以 Vite 建置、Tailwind 排版，部署於 Azure Static Web Apps。後端是 Django REST Framework，以 Linux Container 形式部署於 Azure App Service，由 gunicorn 以非 root 使用者執行。資料層分為兩部分：文件中繼資料存於 PostgreSQL，文件全文與向量存於 Azure AI Search，原始檔案存於 Azure Blob Storage。

## 服務層設計原則

所有 Azure SDK 呼叫都封裝在 `services/` 目錄，View 層不直接接觸任何 SDK 客戶端。這樣做有三個好處：測試時只要 patch 服務類別就能完全隔離付費 API；更換 Azure 服務或 SDK 版本時只需改動單一檔案；View 層維持精簡，只負責驗證輸入與組裝回應。

服務層共有四個模組。`openai_service.py` 負責 Chat Completion 與 Embedding 生成。`search_service.py` 負責向量索引管理與混合搜尋。`blob_service.py` 負責檔案上傳、SAS Token 簽發與依 MIME 類型路由文字抽取。`document_intelligence_service.py` 負責 PDF 的文字與表格抽取。

Azure SDK 拋出的例外一律在服務層邊界轉換為應用程式定義的例外型別，例如 `SearchServiceError`、`BlobServiceError`、`OpenAIServiceError`。View 層只捕捉這些應用層例外，不需理解 Azure SDK 的例外階層。外部 API 呼叫透過 `tenacity` 加入指數退避重試，最多嘗試三次。

## 文件抽取路由

`blob_service.extract_text()` 依 MIME 類型分派處理方式。`application/pdf` 交給 Azure Document Intelligence 的 `prebuilt-layout` 模型，這個模型會把表格結構保留為 Markdown 格式，避免表格在純文字抽取後變成無意義的數字串。`text/plain` 直接以 UTF-8 解碼。DOCX 以 `python-docx` 逐段落抽取。不支援的類型直接拋出 `BlobServiceError`，不做猜測性處理。

Document Intelligence 是延遲匯入（lazy import），因為未設定該服務時仍應能處理 TXT 與 DOCX，不該因為缺少設定而讓整個模組無法載入。

## Blob 路徑慣例

Blob 路徑固定為 `{user_id}/{document_id}/{filename}`。把 user_id 放在路徑最前面，讓擁有者驗證可以透過前綴查詢完成，不需掃描整個容器；刪除時也能以前綴精確定位，避免越權刪除他人文件。

## 健康檢查

`/api/health/` 是刻意設計得極輕量的端點：不做驗證、不查資料庫、不呼叫任何 Azure 服務，只回傳固定的 JSON。它同時被 Dockerfile 的 HEALTHCHECK 與 App Service 的 liveness probe 使用。如果健康檢查會查資料庫，資料庫短暫抖動就會導致容器被反覆重啟，把小問題放大成服務中斷。
