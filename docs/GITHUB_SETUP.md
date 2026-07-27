# GitHub 設定檢查清單（面試導向）

面試官打開你的 repo 時，通常在 30 秒內就形成判斷：README 說不說得清楚這是什麼、CI 是不是綠的、commit 歷史像不像一個工程師的工作方式。這份清單把這些訊號逐項補齊。

依序執行即可。

---

## 0. 先確認 commit email 會連到你的 GitHub 帳號

**這一步必須在 push 之前處理。** 本機 git 目前的 email 是：

```bash
git config user.email
# ken1987413@gmail.com
```

GitHub 只會把 commit 歸屬到**該帳號已驗證的 email**。如果上面這個 email 沒有註冊在你要展示的帳號下，這些 commit 在網頁上會顯示為無頭像的陌生使用者，而且**不會計入你的貢獻圖**——面試官看到的會是一個「沒有作者」的專案。

兩個選項，擇一：

**選項 A — 把這個 email 加到 GitHub 帳號**（最省事）

到 Settings → Emails 新增 `ken1987413@gmail.com` 並完成驗證。現有 commit 立刻正確歸屬，不需改寫歷史。

**選項 B — 改用帳號已驗證的 email 並改寫歷史**

因為還沒 push，改寫歷史零成本：

```bash
# 設定本 repo 專用的身分（不影響其他專案）
git config user.email "<你 GitHub 帳號已驗證的 email>"
git config user.name "<你希望顯示的名字>"

# 用新身分改寫全部既有 commit
git rebase --root --exec 'git commit --amend --no-edit --reset-author'
```

改完確認：

```bash
git log --format='%an <%ae>' | sort -u
```

只應該出現一組你要的身分。

---

## 1. 重新登入 gh CLI

目前的 token 已失效：

```bash
gh auth status
# X Failed to log in to github.com account zechengze (keyring)
```

重新登入（這一步需要你自己操作，會開啟瀏覽器驗證）：

```bash
gh auth login -h github.com
```

---

## 2. 建立 repo 並 push

```bash
gh repo create azure-rag-assistant \
  --public \
  --source . \
  --remote origin \
  --description "企業級 RAG 知識問答系統 — Azure OpenAI + AI Search 混合檢索、SSE 串流、多租戶隔離。Django REST Framework / React / AZ-204 實作專案" \
  --push
```

push 前最後確認一次沒有機密外洩：

```bash
git ls-files | grep -Ei '\.env$|\.env\.local|provision\.env|\.pem$|\.key$'
# 應該沒有任何輸出
```

---

## 3. About 區塊與 Topics

Topics 是 GitHub 站內搜尋與「這個人做什麼」的第一層訊號：

```bash
gh repo edit --add-topic azure,azure-openai,azure-ai-search,rag,django,django-rest-framework,react,typescript,az-204,vector-search,llm
```

Demo 上線後補上網址（會顯示在 repo 右上角，是最容易被點擊的位置）：

```bash
gh repo edit --homepage "https://<your-swa>.azurestaticapps.net"
```

---

## 4. 安全設定

這個專案的賣點之一就是資安實踐（CLAUDE.md 有整節規範），把對應的 GitHub 功能打開，說法才站得住：

```bash
gh api -X PATCH repos/{owner}/{repo} \
  -F security_and_analysis[secret_scanning][status]=enabled \
  -F security_and_analysis[secret_scanning_push_protection][status]=enabled
```

- **Secret scanning**：掃描已提交的金鑰
- **Push protection**：在 push 當下就阻擋含金鑰的 commit（這是真正有用的那一個）

Dependabot 在 Settings → Code security 開啟 **Dependabot alerts** 與 **security updates**。

若要讓依賴更新自動開 PR，加上 `.github/dependabot.yml`（pip + npm 各一個 ecosystem）。面試角度看，這會讓 repo 有真實的 PR 活動記錄。

---

## 5. 建立 production environment

兩個部署 workflow 都綁在名為 `production` 的 environment：

Settings → Environments → New environment → 命名 `production`。

OIDC 的 federated credential subject 必須與此一致，詳見 [DEPLOYMENT.md](./DEPLOYMENT.md)。

---

## 6. Branch protection

讓 main 只能透過 PR 更新、且 CI 必須綠燈：

```bash
gh api -X PUT repos/{owner}/{repo}/branches/main/protection \
  --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["Backend (Python 3.11)", "Frontend"]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
```

> `contexts` 必須與 CI job 的顯示名稱完全一致。第一次 CI 跑完後，用 `gh run view --json jobs` 確認實際名稱。
>
> **單人專案的注意事項**：`required_approving_review_count: 1` 會讓你自己也無法合併自己的 PR（GitHub 不允許自我 approve）。若確定要走 PR 流程但沒有第二個人，把這個欄位改成 `0`，保留「必須開 PR + CI 綠燈」的約束即可。

設定完成後，接下來的改動都走 feature branch + PR。面試官看到的會是真實的協作流程，而不是 30 個直推 main 的 commit。

---

## 7. Profile 置頂

到你的 GitHub 首頁 → Customize your pins，把這個 repo 設為置頂。沒有置頂的話，它會被埋在依最後更新時間排序的清單裡。

---

## 面試官會看什麼

逐項自我檢查：

- [ ] README 第一屏就有 **Live Demo 連結 + demo 帳密**，不需要問你就能操作
- [ ] CI badge 是綠的（badge 的 `<owner>/<repo>` 佔位符已替換為實際值）
- [ ] 架構圖能直接當技術討論的起點（mermaid 在 GitHub 上原生渲染）
- [ ] commit 歷史是可讀的 Conventional Commits，不是一顆 "initial commit"
- [ ] 有 LICENSE、有 topics、About 區塊填了 demo 網址
- [ ] 資安相關功能實際開啟，不只寫在文件裡
- [ ] 測試覆蓋率門檻由 CI 強制（`--cov-fail-under=70`），不是口頭聲稱

---

## 可以主動講的技術決策

這些都是 repo 裡有實際程式碼支撐、面試中容易展開的點：

| 主題 | 可以講的內容 |
|---|---|
| 為什麼混合搜尋 | 純向量搜尋在專有名詞、錯誤代碼上會失準；純 BM25 無法處理同義改寫。向量端過召回 2K 再重排 |
| Prompt injection 防護 | 召回文件只注入 System Prompt。放進 User Message 的話，惡意文件就能偽裝成使用者指令 |
| 機密管理 | Managed Identity + Key Vault，程式碼裡沒有「用來取得其他機密的機密」。只有 5 個真正的機密走 Key Vault，因為它按交易計費 |
| 多租戶隔離 | 過濾發生在搜尋引擎端而非應用程式端，不屬於該使用者的段落根本不會回到後端 |
| 部署認證 | OIDC federated credential，repo 內沒有長期有效的密碼 |
| 健康檢查設計 | 刻意不查 DB。若查了，資料庫短暫抖動就會讓容器被反覆重啟，把小問題放大成服務中斷 |
| 部署驗證 | CD 會輪詢 `/api/health/`；只看「映像推送成功」會把啟動失敗的部署誤判為成功 |
| AI 輔助開發 | CLAUDE.md 定義規範，AI 產出的程式碼仍須通過 black / flake8 / mypy / 70% 覆蓋率門檻，資安邏輯一律人工複審 |
