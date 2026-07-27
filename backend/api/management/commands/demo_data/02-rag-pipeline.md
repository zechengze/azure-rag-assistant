# RAG 檢索與生成流程

## 完整資料流

使用者送出查詢後，流程依序是：輸入驗證、查詢向量化、Azure AI Search 混合檢索、文件段落召回、Prompt 組裝、Azure OpenAI 生成、回應串流回前端。

## 輸入驗證

查詢先經過 DRF Serializer 驗證，限制最長 2000 字元，並執行 prompt injection 偵測。長度限制同時是成本控制手段：過長的查詢會放大 embedding 與 completion 的 token 用量。

## Chunking 策略

文件切分為每段最多 512 單位、相鄰段落重疊 128 單位。切分以句子邊界為準，用正規表示式在句號、問號、驚嘆號（全形與半形皆涵蓋）之後斷開，避免在句子中間截斷導致語意破碎。

重疊的作用是避免答案剛好跨在兩個 chunk 的交界處而被切斷。重疊設為 chunk 大小的四分之一，是召回品質與索引體積之間的折衷：重疊越多，索引儲存與 embedding 成本越高。

## 混合搜尋

檢索同時使用關鍵字與語意兩種訊號。Azure AI Search 以 BM25 處理關鍵字比對，向量搜尋則用 HNSW 演算法做近似最近鄰搜尋。兩者結果合併重排後取前 5 段。

向量查詢刻意過召回：`k_nearest_neighbors` 設為 `top_k * 2`，也就是先取 10 筆再重排到 5 筆。單獨使用向量搜尋時，專有名詞、產品代號、錯誤代碼這類字面比對很重要的查詢容易失準；單獨使用 BM25 則無法處理同義改寫。混合搜尋讓兩種弱點互補。

索引的 `title` 與 `content` 欄位都指定 `zh-Hant.lucene` 分析器，讓中文斷詞正確。向量欄位維度為 1536，對應 `text-embedding-3-small` 的輸出。

## 多租戶隔離

每個索引 chunk 都帶有 `user_id` 欄位，搜尋時以 `filter=user_id eq '<id>'` 過濾。過濾發生在搜尋引擎端而非應用程式端，意思是不屬於該使用者的段落根本不會回到後端，也就不可能被誤放進 prompt。資料庫層則以 `Document.objects.filter(user=request.user, is_active=True)` 做對應的隔離。

## 模型選擇

開發環境使用 `gpt-4.1-mini` 與 `text-embedding-3-small`（1536 維）以壓低成本，生產環境可切換為 `gpt-4.1` 與 `text-embedding-3-large`。切換 embedding 模型會改變向量維度，因此必須重建索引並重新索引所有文件，不能只改設定。

## 串流回應

聊天端點支援 `stream=true`，以 Server-Sent Events 逐 token 回傳，前端呈現打字機效果。回應會設定 `Cache-Control: no-cache` 與 `X-Accel-Buffering: no`，後者是為了關閉反向代理的緩衝，否則 token 會被累積成一整塊才送出，串流效果完全消失。串流結束以 `data: [DONE]` 標記，錯誤則以 `data: [ERROR] <訊息>` 傳遞，讓前端能區分正常結束與異常中斷。
