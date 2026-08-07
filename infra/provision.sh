#!/usr/bin/env bash
#
# 建立 Azure RAG Knowledge Assistant 的 demo 環境。
#
# 本腳本為 idempotent：重複執行只會補齊缺少的資源，已存在者跳過。
# 所有資源建立在單一 resource group 內，面試結束後一次刪除即可停止計費：
#   az group delete --name <RESOURCE_GROUP> --yes
#
# 前置需求：az CLI 已登入 (az login) 且已選定訂閱。
# 用法：
#   cp infra/provision.env.example infra/provision.env   # 編輯後
#   ./infra/provision.sh
#
# 本腳本刻意「不」建立 Azure OpenAI 與 Document Intelligence 資源：
# 這兩者的區域可用性與配額申請無法可靠自動化，須於 Portal 手動建立後
# 把端點與金鑰填入 provision.env。詳見 docs/DEPLOYMENT.md。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/provision.env"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "找不到 ${ENV_FILE}" >&2
  echo "請先複製 provision.env.example 並填入實際值。" >&2
  exit 1
fi

# shellcheck source=/dev/null
source "${ENV_FILE}"

: "${RESOURCE_GROUP:?provision.env 未設定 RESOURCE_GROUP}"
: "${LOCATION:?provision.env 未設定 LOCATION}"
: "${APP_NAME:?provision.env 未設定 APP_NAME}"
: "${STORAGE_ACCOUNT:?provision.env 未設定 STORAGE_ACCOUNT}"
: "${SEARCH_SERVICE:?provision.env 未設定 SEARCH_SERVICE}"
: "${KEY_VAULT:?provision.env 未設定 KEY_VAULT}"
: "${GITHUB_REPO:?provision.env 未設定 GITHUB_REPO (格式 owner/repo)}"

log() { printf '\n\033[1;34m==> %s\033[0m\n' "$1"; }

# ─────────────────────────────────────────────────────────────────────────────
log "Resource group: ${RESOURCE_GROUP}"
az group create --name "${RESOURCE_GROUP}" --location "${LOCATION}" --output none

# ─────────────────────────────────────────────────────────────────────────────
# 這裡刻意不建立 Azure Container Registry：ACR 即使是 Basic 層也是每月約 $5
# 的固定費用（與推送次數、儲存量無關），在這個 demo 的帳單裡佔比接近全部。
# 映像改推 ghcr.io/<owner>/azure-rag-assistant（公開映像不計費），
# 由 deploy-backend.yml 用 GITHUB_TOKEN 推送，App Service 匿名拉取。
# ─────────────────────────────────────────────────────────────────────────────
log "Storage account: ${STORAGE_ACCOUNT}"
if ! az storage account show \
  --name "${STORAGE_ACCOUNT}" \
  --resource-group "${RESOURCE_GROUP}" --output none 2>/dev/null; then
  az storage account create \
    --name "${STORAGE_ACCOUNT}" \
    --resource-group "${RESOURCE_GROUP}" \
    --location "${LOCATION}" \
    --sku Standard_LRS \
    --kind StorageV2 \
    --min-tls-version TLS1_2 \
    --allow-blob-public-access false \
    --output none
fi

STORAGE_CONNECTION_STRING=$(
  az storage account show-connection-string \
    --name "${STORAGE_ACCOUNT}" \
    --resource-group "${RESOURCE_GROUP}" \
    --query connectionString --output tsv
)

# ─────────────────────────────────────────────────────────────────────────────
# Free tier 每個訂閱僅限一個 search service，且不支援升級——
# 若已有其他 free service，此步驟會失敗，需改用 --sku basic (約 $75/月)。
log "AI Search: ${SEARCH_SERVICE} (free tier)"
if ! az search service show \
  --name "${SEARCH_SERVICE}" \
  --resource-group "${RESOURCE_GROUP}" --output none 2>/dev/null; then
  az search service create \
    --name "${SEARCH_SERVICE}" \
    --resource-group "${RESOURCE_GROUP}" \
    --location "${LOCATION}" \
    --sku free \
    --output none
fi

SEARCH_KEY=$(
  az search admin-key show \
    --service-name "${SEARCH_SERVICE}" \
    --resource-group "${RESOURCE_GROUP}" \
    --query primaryKey --output tsv
)

# ─────────────────────────────────────────────────────────────────────────────
log "Key Vault: ${KEY_VAULT}"
if ! az keyvault show --name "${KEY_VAULT}" --output none 2>/dev/null; then
  az keyvault create \
    --name "${KEY_VAULT}" \
    --resource-group "${RESOURCE_GROUP}" \
    --location "${LOCATION}" \
    --enable-rbac-authorization true \
    --output none
fi

# 授予執行者寫入機密的權限（RBAC 生效有數十秒延遲）
CALLER_ID=$(az ad signed-in-user show --query id --output tsv)
VAULT_SCOPE=$(az keyvault show --name "${KEY_VAULT}" --query id --output tsv)
az role assignment create \
  --assignee "${CALLER_ID}" \
  --role "Key Vault Secrets Officer" \
  --scope "${VAULT_SCOPE}" \
  --output none 2>/dev/null || true

echo "等待 RBAC 生效..."
sleep 30

# ─────────────────────────────────────────────────────────────────────────────
# 機密名稱轉換規則見 core/secrets.py：底線改為連字號、全部小寫。
log "寫入機密至 Key Vault"
set_secret() {
  local name="$1" value="$2"
  if [[ -z "${value}" ]]; then
    echo "  略過 ${name} (值為空)"
    return
  fi
  az keyvault secret set \
    --vault-name "${KEY_VAULT}" \
    --name "${name}" \
    --value "${value}" \
    --output none
  echo "  已設定 ${name}"
}

# Cognitive Services 的金鑰直接向 Azure 索取,provision.env 因此不必存放機密。
# 只有在 provision.env 明確設了 *_KEY 時才沿用該值(例如資源不在此訂閱下)。
resolve_cognitive_key() {
  local account="$1" account_rg="$2"
  if [[ -z "${account}" ]]; then
    return 0
  fi
  az cognitiveservices account keys list \
    --name "${account}" \
    --resource-group "${account_rg:-${RESOURCE_GROUP}}" \
    --query key1 --output tsv 2>/dev/null || true
}

if [[ -z "${AZURE_OPENAI_KEY:-}" ]]; then
  AZURE_OPENAI_KEY=$(resolve_cognitive_key \
    "${AZURE_OPENAI_ACCOUNT:-}" "${AZURE_OPENAI_ACCOUNT_RG:-}")
  [[ -n "${AZURE_OPENAI_KEY}" ]] && echo "  已自動取得 Azure OpenAI 金鑰"
fi

if [[ -z "${AZURE_DOCUMENT_INTELLIGENCE_KEY:-}" ]]; then
  AZURE_DOCUMENT_INTELLIGENCE_KEY=$(resolve_cognitive_key \
    "${AZURE_DOCUMENT_INTELLIGENCE_ACCOUNT:-}" \
    "${AZURE_DOCUMENT_INTELLIGENCE_ACCOUNT_RG:-}")
  [[ -n "${AZURE_DOCUMENT_INTELLIGENCE_KEY}" ]] &&
    echo "  已自動取得 Document Intelligence 金鑰"
fi

DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-$(openssl rand -base64 48 | tr -d '\n')}"

set_secret "secret-key" "${DJANGO_SECRET_KEY}"
set_secret "azure-search-key" "${SEARCH_KEY}"
set_secret "azure-storage-connection-string" "${STORAGE_CONNECTION_STRING}"
set_secret "azure-openai-key" "${AZURE_OPENAI_KEY:-}"
set_secret "azure-document-intelligence-key" "${AZURE_DOCUMENT_INTELLIGENCE_KEY:-}"

# ─────────────────────────────────────────────────────────────────────────────
log "App Service plan + web app: ${APP_NAME}"
if ! az appservice plan show \
  --name "asp-${APP_NAME}" \
  --resource-group "${RESOURCE_GROUP}" --output none 2>/dev/null; then
  az appservice plan create \
    --name "asp-${APP_NAME}" \
    --resource-group "${RESOURCE_GROUP}" \
    --location "${LOCATION}" \
    --is-linux \
    --sku B1 \
    --output none
fi

if ! az webapp show \
  --name "${APP_NAME}" \
  --resource-group "${RESOURCE_GROUP}" --output none 2>/dev/null; then
  # 首次建立先用公開的 hello-world 映像：此時 ghcr 上還沒有任何映像，
  # 指向不存在的 tag 會讓 web app 卡在啟動失敗狀態。
  # 真正的映像位址由 deploy-backend.yml 在首次部署時設定。
  az webapp create \
    --name "${APP_NAME}" \
    --resource-group "${RESOURCE_GROUP}" \
    --plan "asp-${APP_NAME}" \
    --container-image-name "mcr.microsoft.com/azuredocs/aci-helloworld:latest" \
    --output none
fi

# ─────────────────────────────────────────────────────────────────────────────
log "啟用 Managed Identity 並授權存取 Key Vault"
PRINCIPAL_ID=$(
  az webapp identity assign \
    --name "${APP_NAME}" \
    --resource-group "${RESOURCE_GROUP}" \
    --query principalId --output tsv
)

# 只給讀取權限：應用程式需要讀機密，不需要建立或刪除。
az role assignment create \
  --assignee "${PRINCIPAL_ID}" \
  --role "Key Vault Secrets User" \
  --scope "${VAULT_SCOPE}" \
  --output none 2>/dev/null || true

# 映像放在 ghcr.io 的公開套件，拉取不需要任何憑證，因此必須關掉 Managed
# Identity 拉取——留著 true 時 App Service 會試圖拿 Azure AD token 去跟
# ghcr 認證並失敗。從舊的 ACR 設定遷移過來時這步是必要的，不是預設值。
az resource update \
  --ids "$(az webapp show --name "${APP_NAME}" \
            --resource-group "${RESOURCE_GROUP}" --query id --output tsv)/config/web" \
  --set properties.acrUseManagedIdentityCreds=false \
  --output none

# ─────────────────────────────────────────────────────────────────────────────
log "設定應用程式環境變數"
FRONTEND_ORIGIN="${FRONTEND_ORIGIN:-https://${APP_NAME}.azurestaticapps.net}"

az webapp config appsettings set \
  --name "${APP_NAME}" \
  --resource-group "${RESOURCE_GROUP}" \
  --settings \
    DEBUG=False \
    ALLOWED_HOSTS="${APP_NAME}.azurewebsites.net" \
    CORS_ALLOWED_ORIGINS="${FRONTEND_ORIGIN}" \
    AZURE_KEY_VAULT_URL="https://${KEY_VAULT}.vault.azure.net/" \
    AZURE_SEARCH_ENDPOINT="https://${SEARCH_SERVICE}.search.windows.net" \
    AZURE_SEARCH_INDEX_NAME="${SEARCH_INDEX_NAME:-knowledge-base}" \
    AZURE_STORAGE_CONTAINER="${STORAGE_CONTAINER:-documents}" \
    AZURE_STORAGE_SAS_EXPIRY_HOURS=1 \
    AZURE_OPENAI_ENDPOINT="${AZURE_OPENAI_ENDPOINT:-}" \
    AZURE_OPENAI_CHAT_DEPLOYMENT="${AZURE_OPENAI_CHAT_DEPLOYMENT:-gpt-4.1-mini}" \
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT="${AZURE_OPENAI_EMBEDDING_DEPLOYMENT:-text-embedding-3-small}" \
    AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT="${AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT:-}" \
    THROTTLE_CHAT="${THROTTLE_CHAT:-15/hour}" \
    THROTTLE_USER="${THROTTLE_USER:-60/hour}" \
    DATABASE_URL="${DATABASE_URL:-sqlite:////home/db.sqlite3}" \
    WEBSITES_PORT=8000 \
    WEBSITES_ENABLE_APP_SERVICE_STORAGE=true \
  --output none
# ↑ 自訂容器預設不掛載持久化的 /home;預設資料庫 sqlite:////home/db.sqlite3
#   依賴這個掛載,關閉時 /home 只是映像內 root 擁有的目錄,非 root 的
#   appuser 無法寫入,migrate 會在啟動時失敗。

# migrate 放在啟動腳本而非映像 CMD：映像因此保持與環境無關，
# 同一個 image 可以在本機、CI 與 Azure 用不同的啟動方式跑。
# 注意：這裡必須是單一路徑，不能是 inline 指令 —— App Service 會對
# appCommandLine 自行斷詞，巢狀引號會被拆壞，容器以 exit 2 秒退。
az webapp config set \
  --name "${APP_NAME}" \
  --resource-group "${RESOURCE_GROUP}" \
  --startup-file "/app/startup.sh" \
  --output none

az webapp config set \
  --name "${APP_NAME}" \
  --resource-group "${RESOURCE_GROUP}" \
  --http20-enabled true \
  --min-tls-version 1.2 \
  --ftps-state Disabled \
  --output none

# ─────────────────────────────────────────────────────────────────────────────
log "設定 GitHub Actions 的 OIDC federated credential"
APP_REG_NAME="gh-${APP_NAME}-deploy"
CLIENT_ID=$(
  az ad app list --display-name "${APP_REG_NAME}" --query "[0].appId" --output tsv
)
if [[ -z "${CLIENT_ID}" ]]; then
  CLIENT_ID=$(
    az ad app create --display-name "${APP_REG_NAME}" --query appId --output tsv
  )
  az ad sp create --id "${CLIENT_ID}" --output none
fi

SUBSCRIPTION_ID=$(az account show --query id --output tsv)
TENANT_ID=$(az account show --query tenantId --output tsv)

# 部署權限限縮在此 resource group，不給訂閱層級權限
az role assignment create \
  --assignee "${CLIENT_ID}" \
  --role Contributor \
  --scope "/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}" \
  --output none 2>/dev/null || true

ensure_federated_credential() {
  local name="$1" subject="$2"
  if az ad app federated-credential list --id "${CLIENT_ID}" \
       --query "[?name=='${name}']" --output tsv | grep -q .; then
    echo "  已存在 ${name}"
    return
  fi
  az ad app federated-credential create \
    --id "${CLIENT_ID}" \
    --parameters "{
      \"name\": \"${name}\",
      \"issuer\": \"https://token.actions.githubusercontent.com\",
      \"subject\": \"${subject}\",
      \"audiences\": [\"api://AzureADTokenExchange\"]
    }" --output none
  echo "  已建立 ${name}"
}

# GitHub 現以「immutable ID」形式簽發 OIDC subject：
#   repo:<owner>@<owner_id>/<repo>@<repo_id>:environment:production
# 與可讀形式 repo:<owner>/<repo>:... 不同，只註冊後者會得到 AADSTS700213。
# 兩種都註冊：可讀形式仍適用於較舊的租戶設定，多註冊沒有成本。
GH_META=$(curl -fsSL "https://api.github.com/repos/${GITHUB_REPO}" 2>/dev/null || true)
GH_IDS=$(
  printf '%s' "${GH_META}" | python3 -c \
    'import sys,json;d=json.load(sys.stdin);print(d["owner"]["id"],d["id"])' \
    2>/dev/null || true
)

# subject 綁定 repo 與分支/environment：只有 main 分支或 production
# environment 的 workflow 能換到 token
ensure_federated_credential "github-main" \
  "repo:${GITHUB_REPO}:ref:refs/heads/main"
# workflow 使用 environment: production 時 subject 會改為 environment 形式
ensure_federated_credential "github-env-production" \
  "repo:${GITHUB_REPO}:environment:production"

if [[ -n "${GH_IDS}" ]]; then
  read -r OWNER_ID REPO_ID <<<"${GH_IDS}"
  GH_OWNER="${GITHUB_REPO%%/*}"
  GH_NAME="${GITHUB_REPO##*/}"
  IMMUTABLE_PREFIX="repo:${GH_OWNER}@${OWNER_ID}/${GH_NAME}@${REPO_ID}"
  ensure_federated_credential "github-main-immutable" \
    "${IMMUTABLE_PREFIX}:ref:refs/heads/main"
  ensure_federated_credential "github-env-production-immutable" \
    "${IMMUTABLE_PREFIX}:environment:production"
else
  echo "  警告：查不到 ${GITHUB_REPO} 的數值 ID（repo 為私有或無網路？）," >&2
  echo "        未註冊 immutable 形式的 subject。若 workflow 出現" >&2
  echo "        AADSTS700213，請從錯誤訊息中的 subject 手動補註冊。" >&2
fi

# ─────────────────────────────────────────────────────────────────────────────
cat <<EOF

────────────────────────────────────────────────────────────────────
完成。接著在 GitHub 設定以下項目：

gh variable set AZURE_RESOURCE_GROUP --body "${RESOURCE_GROUP}"
gh variable set WEBAPP_NAME          --body "${APP_NAME}"
gh variable set VITE_API_URL         --body "https://${APP_NAME}.azurewebsites.net"

gh secret set AZURE_CLIENT_ID       --body "${CLIENT_ID}"
gh secret set AZURE_TENANT_ID       --body "${TENANT_ID}"
gh secret set AZURE_SUBSCRIPTION_ID --body "${SUBSCRIPTION_ID}"

首次部署後，把 ghcr 套件改為 Public（App Service 是匿名拉取，套件預設為
private 會讓容器一直拉不到映像）：
  https://github.com/users/${GITHUB_REPO%%/*}/packages/container/azure-rag-assistant/settings

後端網址：https://${APP_NAME}.azurewebsites.net
健康檢查：https://${APP_NAME}.azurewebsites.net/api/health/

Static Web App 需另外建立 (見 docs/DEPLOYMENT.md 步驟 5)。
面試結束後停止計費：
  az group delete --name ${RESOURCE_GROUP} --yes --no-wait
────────────────────────────────────────────────────────────────────
EOF
