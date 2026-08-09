# 部署指引

把本專案架成一個公開可瀏覽的 demo：後端跑在 App Service Linux Container，前端跑在 Static Web Apps，兩者都由 GitHub Actions 自動部署。

目標是**面試官點開網址就能直接操作**，而不是只能看螢幕截圖。

---

## 架構與費用

| 元件 | 服務 / 方案 | 約略月費 |
|---|---|---|
| 後端 | App Service Linux Container，B1 | ~$13 |
| 容器映像 | GitHub Container Registry，**公開套件** | $0 |
| 向量檢索 | AI Search，**Free**（50 MB、3 索引） | $0 |
| 檔案儲存 | Storage Account，Standard_LRS | < $1 |
| 機密管理 | Key Vault（依交易計費） | < $1 |
| 前端 | Static Web Apps，**Free** | $0 |
| 資料庫 | App Service 檔案系統上的 SQLite | $0 |
| AI 推論 | Azure OpenAI，按 token 計費 | demo 流量下 ~$1–3 |

合計約 **$15–20/月**，其中 App Service plan 佔九成以上。實際金額依區域與用量而異，請以 Azure Pricing Calculator 與帳單為準。

**為什麼不用 Azure Container Registry**：ACR 連最低的 Basic 層都是每月約 $5 的**固定**費用，與推送次數、儲存量都無關。這個專案一個月推不到幾次映像，卻要為此付掉整體帳單的一大塊——實測某個月的帳單裡 ACR 佔了 98%。改推 ghcr.io 的公開套件後這一項歸零，代價只是映像必須公開（對一個本來就開源的作品集專案而言不是代價）。用 ACR 的理由通常是 Managed Identity 拉取、私有網路、與 Azure 的區域親和性——demo 環境都用不到。

**資料庫的取捨**：預設用 `/home` 上的 SQLite（App Service 的 `/home` 是持久化儲存），月費為零。要在面試中示範 Azure Database for PostgreSQL，把 `provision.env` 的 `DATABASE_URL` 指向 Flexible Server（B1ms 約 $13/月）即可，程式碼不需改動——`dj_database_url` 直接吃連線字串。

**AI Search Free tier 的限制**：每個訂閱只能有一個 free service，且無法原地升級。若該訂閱已用掉這個額度，`provision.sh` 會在建立 search service 時失敗，需改用 `--sku basic`（約 $75/月）。

---

## 步驟 1：手動建立 AI 服務

Azure OpenAI 與 Document Intelligence 沒有納入 `provision.sh`，因為區域可用性與配額申請無法可靠自動化。

在 Portal 建立：

1. **Azure OpenAI** 資源，並在 Azure AI Foundry 部署兩個模型：
   - Chat：`gpt-4.1-mini`（部署名稱請與 `AZURE_OPENAI_CHAT_DEPLOYMENT` 一致）
   - Embedding：`text-embedding-3-small`（1536 維，與 `search_service.py` 的索引定義相符）
2. **Document Intelligence** 資源（供 PDF 表格抽取；只 demo TXT 問答的話可略過）

記下兩者的 endpoint 與 key。

> 切換 embedding 模型會改變向量維度，必須重建索引並重新索引所有文件，不能只改設定。

---

## 步驟 2：佈建其餘資源

```bash
cp infra/provision.env.example infra/provision.env
```

編輯 `infra/provision.env`，填入步驟 1 的值與各項全域唯一名稱（Storage、Key Vault 的名稱在整個 Azure 中不可重複）。`provision.env` 已列入 `.gitignore`。

```bash
az login
az account set --subscription "<your-subscription>"
./infra/provision.sh
```

腳本是 idempotent 的，中途失敗修正後可直接重跑。它會建立 resource group、Storage、AI Search、Key Vault、App Service（含 plan），並且：

- 為 web app 啟用 **Managed Identity**，授予 Key Vault 的 `Key Vault Secrets User`（映像放在 ghcr 公開套件，拉取不需憑證，故 `acrUseManagedIdentityCreds` 設為關閉；`deploy-backend.yml` 每次部署也會重設，設定漂掉會自己修回來）
- 把 5 個機密寫入 Key Vault（名稱依 `core/secrets.py` 的規則把底線轉為連字號）
- 設定 App Service 環境變數，其中 `AZURE_KEY_VAULT_URL` 一設定，應用程式就改從 Key Vault 解析機密
- 建立 **OIDC federated credential** 供 GitHub Actions 使用

執行完畢會印出下一步要設定的 GitHub 變數，直接複製貼上即可。

### 為什麼是 OIDC 而不是存 service principal 密碼

Federated credential 讓 GitHub 為每次 workflow run 簽發短效期 token，換取 Azure access token。儲存庫裡因此只有 client id、tenant id、subscription id，**沒有任何長期有效的密碼**，也沒有輪替負擔。

腳本註冊了兩個 subject：`ref:refs/heads/main` 與 `environment:production`。因為 workflow 使用了 `environment: production`，OIDC token 的 subject 會變成 environment 形式；只註冊分支形式會導致登入失敗。

---

## 步驟 3：設定 GitHub 變數與機密

用 `provision.sh` 輸出的值執行：

```bash
gh variable set AZURE_RESOURCE_GROUP --body "rg-rag-assistant"
gh variable set WEBAPP_NAME          --body "<your-app-name>"
gh variable set VITE_API_URL         --body "https://<your-app-name>.azurewebsites.net"

gh secret set AZURE_CLIENT_ID       --body "<client-id>"
gh secret set AZURE_TENANT_ID       --body "<tenant-id>"
gh secret set AZURE_SUBSCRIPTION_ID --body "<subscription-id>"
```

另外在 GitHub 建立名為 `production` 的 Environment（Settings → Environments），兩個部署 workflow 都綁在這個 environment 上。

---

## 步驟 4：首次部署後端

```bash
git push origin main
```

或手動觸發：

```bash
gh workflow run deploy-backend.yml
```

Workflow 會建置映像、推上 `ghcr.io/<owner>/azure-rag-assistant`、更新 App Service 的容器設定、重啟，然後輪詢 `/api/health/` 最多 5 分鐘。**健康檢查沒通過就算部署失敗**——少了這一步，映像推送成功但容器啟動失敗的部署會被誤判為綠燈。

### 首次部署後：把套件改為 Public

**這一步不做，第一次部署一定會卡在健康檢查失敗。** ghcr 的套件預設是 private，而 App Service 是以匿名身分拉取映像。

推送成功後（映像存在了，套件才會出現），到：

```
https://github.com/users/<owner>/packages/container/azure-rag-assistant/settings
```

在 **Danger Zone → Change package visibility** 改為 **Public**，然後重跑一次 workflow 或重啟 web app。這是一次性設定，之後的部署都不需要再處理。

> 想維持映像私有的話，就得給 App Service 一組有 `read:packages` 權限的 PAT（`--container-registry-user/--container-registry-password`）。那等於在 Azure 上放一組會過期、需要輪替的長期憑證，與本專案「儲存庫內沒有長期密碼」的做法相衝突，所以這裡選擇公開映像。

驗證：

```bash
curl https://<your-app-name>.azurewebsites.net/api/health/
# {"status":"ok"}
```

失敗時看容器日誌：

```bash
az webapp log tail --name <your-app-name> --resource-group rg-rag-assistant --provider docker
```

---

## 步驟 5：建立 Static Web App 並部署前端

```bash
az staticwebapp create \
  --name swa-rag-assistant \
  --resource-group rg-rag-assistant \
  --location eastasia \
  --sku Free

# 取得部署 token 並寫入 GitHub
TOKEN=$(az staticwebapp secrets list \
  --name swa-rag-assistant \
  --query "properties.apiKey" --output tsv)
gh secret set AZURE_STATIC_WEB_APPS_API_TOKEN --body "$TOKEN"
```

> `--location` 只影響 SWA 的後端託管區域，可用區域比一般服務少（如 eastasia、eastus2、westeurope）。

取得 SWA 網址，並把它加入後端的 CORS 白名單——否則瀏覽器會擋掉所有 API 請求：

```bash
SWA_URL=$(az staticwebapp show --name swa-rag-assistant \
  --query "defaultHostname" --output tsv)

az webapp config appsettings set \
  --name <your-app-name> --resource-group rg-rag-assistant \
  --settings CORS_ALLOWED_ORIGINS="https://${SWA_URL}"
```

同時把 `FRONTEND_ORIGIN=https://${SWA_URL}` 寫回 `provision.env`，之後重跑腳本才不會把設定蓋掉。

接著部署前端：

```bash
gh workflow run deploy-frontend.yml
```

---

## 步驟 6：建立 demo 資料

沒有這一步，訪客登入後會看到一個空的知識庫，RAG 無從展示。

`seed_demo` 會索引 `backend/api/management/commands/demo_data/` 底下說明本系統架構的語料，讓 demo 能回答關於自己的問題。

由於預設資料庫是 App Service 檔案系統上的 SQLite，指令必須在容器內執行。

**不要用 `az webapp ssh`**：那需要映像內含 `openssh-server`，而本專案的 `python:3.11-slim` 基底刻意不安裝 sshd（縮小攻擊面）。Kudu 的 `/api/command` 也不行——它跑在另一個容器裡，只共享 `/home`，沒有 `/app` 與應用程式的 Python 環境。

改用啟動腳本執行：設定 `DEMO_PASSWORD` 應用程式設定後，`startup.sh` 會在每次啟動時執行 `seed_demo`。

```bash
az webapp config appsettings set \
  --name <your-app-name> --resource-group rg-rag-assistant \
  --settings DEMO_PASSWORD='<選一個你願意公開的密碼>'
```

密碼須通過 Django 的強度驗證（至少 8 字元、非常見密碼、非純數字），太弱時 `seed_demo` 會拒絕建立帳號並在日誌說明原因——帳號是公開可登入的，弱密碼等同把 Azure 用量開放給整個網際網路。

設定完成會觸發重啟並自動索引。確認結果：

```bash
az webapp log download --name <your-app-name> \
  --resource-group rg-rag-assistant --log-file logs.zip
```

這個設定**保留著**即可：`seed_demo` 以標題比對略過已索引文件，重跑不會重複產生 embedding 費用，卻能讓 `az group delete` 重建後的 demo 自動恢復。

要更換語料或輪替密碼，改設定值後重啟；需要整批重建時在 `startup.sh` 的指令加上 `--reset`。

改用 PostgreSQL 時可直接在本機執行 `DEMO_PASSWORD=... python manage.py seed_demo`（環境變數指向生產服務即可），不受此限。

最後把 demo 帳密寫進 README，讓面試官不必詢問就能登入。

---

## 步驟 7（選用）：Application Insights

```bash
az monitor app-insights component create \
  --app ai-rag-assistant \
  --location eastus \
  --resource-group rg-rag-assistant \
  --application-type web

CONN=$(az monitor app-insights component show \
  --app ai-rag-assistant --resource-group rg-rag-assistant \
  --query connectionString --output tsv)

az webapp config appsettings set \
  --name <your-app-name> --resource-group rg-rag-assistant \
  --settings APPLICATIONINSIGHTS_CONNECTION_STRING="$CONN" \
             ApplicationInsightsAgent_EXTENSION_VERSION="~3"
```

以 App Service 的自動注入方式啟用，不需改動應用程式碼。專案本身已把結構化日誌輸出到 stdout，App Service 會一併收集。

---

## 停止計費

> ⚠️ **`az webapp stop` 不會省到錢。** App Service Plan 是按「已配置」計費，不是按執行時間，停掉 web app 後 plan 照樣每小時計費。Linux 容器又不支援 Free/Shared 層（F1 不能跑自訂容器），所以沒有降級這條路——**要停止計費只能刪掉 plan**。

### 情境一：整個 RG 都是這個 demo 專用

```bash
az group delete --name rg-rag-assistant --yes --no-wait
```

### 情境二：RG 內還有你想保留的資源

若把 demo 部署進既有的 RG（例如沿用已有的 AI Search 免費層實例），**絕對不要刪整個 RG**。只刪掉會計費的運算資源：

```bash
# App Service（$13/月）— plan 必須一起刪，只刪 webapp 仍會計費
az webapp delete --name <APP_NAME> --resource-group <RG>
az appservice plan delete --name asp-<APP_NAME> --resource-group <RG> --yes
```

容器映像放在 ghcr.io，不在 Azure 上，因此不需要（也無從）在這裡刪除；留著也不計費。

Key Vault、Storage、AI Search 免費層、Azure OpenAI（按 token 計費）閒置時幾乎不產生費用，留著即可——也省下重建時的 soft-delete 與免費層額度問題。

重跑 `provision.sh` 就能把刪掉的部分補回來（腳本是 idempotent 的，既存資源會自動略過）。這正是把佈建寫成腳本而非在 Portal 手點的理由：面試前一天用 5 分鐘重建，而不是半小時手動點選還可能漏設定。

---

## 疑難排解

| 症狀 | 原因與處理 |
|---|---|
| workflow 顯示 `AADSTS70021` 或登入失敗 | federated credential 的 subject 與實際不符。確認 workflow 的 `environment:` 與已註冊的 subject 一致 |
| 健康檢查一直 503 | 容器啟動失敗。`az webapp log tail --provider docker` 查看；常見原因是 Key Vault 權限尚未生效或機密名稱拼錯 |
| 容器日誌出現 `unauthorized` 或 `manifest unknown`（ghcr） | ghcr 套件還是 private——見步驟 4 改為 Public。（`acrUseManagedIdentityCreds` 由每次部署自動關閉，不會是原因）|
| 前端能開但 API 全部失敗 | CORS 白名單沒有 SWA 網址，或 `VITE_API_URL` 未設定（bundle 指向 localhost）|
| 上傳 PDF 失敗、TXT 正常 | Document Intelligence 的 endpoint/key 未設定 |
| 聊天回 503 | Azure OpenAI 部署名稱與環境變數不符，或配額用盡 |
| 問答答不出文件內容 | 索引尚未建立或 embedding 維度不符。確認索引存在且模型為 1536 維 |
| 刪掉 RG 後重跑腳本,Key Vault 建立失敗說名稱已被使用 | Key Vault 的 soft-delete 是強制的,刪除後名稱仍被保留 90 天。用 `az keyvault purge --name <name> --location <location>` 徹底清除後再重跑,或換一個名稱 |
| `az ad app create` 權限不足 | 建立 app registration 需要目錄權限,公司租戶常會禁止。改請管理員代建,或在個人訂閱操作 |
