/**
 * 聊天串流請求 —— 與 UI 分離,便於在沒有瀏覽器環境的情況下測試。
 */

import { createSSEParser } from "./sse";

/** 與 useAuth 的 authFetch 同型,呼叫端決定是否附帶 JWT 與 401 重試。 */
export type FetchLike = (input: RequestInfo, init?: RequestInit) => Promise<Response>;

export interface ChatHistoryEntry {
  role: string;
  content: string;
}

export interface StreamChatOptions {
  fetchFn: FetchLike;
  apiBase: string;
  query: string;
  history: ChatHistoryEntry[];
  /** 每收到一個 token 就以「目前累積的完整回答」回呼,供 UI 直接渲染。 */
  onToken: (accumulated: string) => void;
}

/**
 * 送出問題並消費 SSE 串流,回傳完整回答。
 *
 * @throws Error HTTP 狀態非 2xx,或後端回報錯誤事件
 */
export async function streamChat({
  fetchFn,
  apiBase,
  query,
  history,
  onToken,
}: StreamChatOptions): Promise<string> {
  const response = await fetchFn(`${apiBase}/api/chat/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, history, stream: true }),
  });

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }

  const reader = response.body?.getReader();
  if (reader === undefined) {
    return "";
  }

  const decoder = new TextDecoder();
  const parse = createSSEParser();
  let accumulated = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) {
        return accumulated;
      }

      for (const event of parse(decoder.decode(value, { stream: true }))) {
        if (event.type === "token") {
          accumulated += event.value;
          onToken(accumulated);
        } else if (event.type === "done") {
          return accumulated;
        } else {
          throw new Error(event.message);
        }
      }
    }
  } finally {
    // 提早離開 (done 事件或錯誤) 時關閉連線,避免留下未讀取的串流。
    await reader.cancel().catch(() => undefined);
  }
}
