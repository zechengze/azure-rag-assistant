import { describe, expect, it, vi } from "vitest";

import { streamChat, type FetchLike } from "./chat";

/** 以指定的區塊切分方式回傳一個 SSE 串流回應。 */
function sseResponse(chunks: string[], status = 200): Response {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      const encoder = new TextEncoder();
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
  return new Response(stream, {
    status,
    headers: { "Content-Type": "text/event-stream" },
  });
}

function frames(...payloads: unknown[]): string {
  return payloads.map((p) => `data: ${JSON.stringify(p)}\n\n`).join("");
}

describe("streamChat", () => {
  it("完整還原含換行的回答", async () => {
    const tokens = ["這是第一行", "\n\n", "1. 項目一", "\n2. 項目二"];
    const fetchFn: FetchLike = vi.fn(async () =>
      sseResponse([frames(...tokens.map((t) => ({ token: t })), { done: true })]),
    );

    const answer = await streamChat({
      fetchFn,
      apiBase: "http://api.test",
      query: "hi",
      history: [],
      onToken: () => undefined,
    });

    expect(answer).toBe("這是第一行\n\n1. 項目一\n2. 項目二");
  });

  it("串流被切在事件中間時不掉字", async () => {
    const body = frames({ token: "前半" }, { token: "後半" }, { done: true });
    // 逐字元餵入,模擬最惡劣的封包切分。
    const fetchFn: FetchLike = vi.fn(async () => sseResponse([...body]));

    const answer = await streamChat({
      fetchFn,
      apiBase: "http://api.test",
      query: "hi",
      history: [],
      onToken: () => undefined,
    });

    expect(answer).toBe("前半後半");
  });

  it("逐 token 回呼目前累積的完整回答", async () => {
    const fetchFn: FetchLike = vi.fn(async () =>
      sseResponse([frames({ token: "a" }, { token: "b" }, { done: true })]),
    );
    const seen: string[] = [];

    await streamChat({
      fetchFn,
      apiBase: "http://api.test",
      query: "hi",
      history: [],
      onToken: (text) => seen.push(text),
    });

    expect(seen).toEqual(["a", "ab"]);
  });

  it("送出 query、history 與 stream 旗標至 /api/chat/", async () => {
    const fetchFn = vi.fn<FetchLike>(async () => sseResponse([frames({ done: true })]));

    await streamChat({
      fetchFn,
      apiBase: "http://api.test",
      query: "問題",
      history: [{ role: "user", content: "前一題" }],
      onToken: () => undefined,
    });

    const [url, init] = fetchFn.mock.calls[0];
    expect(url).toBe("http://api.test/api/chat/");
    expect(JSON.parse(String(init?.body))).toEqual({
      query: "問題",
      history: [{ role: "user", content: "前一題" }],
      stream: true,
    });
  });

  it("HTTP 錯誤時拋出", async () => {
    const fetchFn: FetchLike = vi.fn(async () => sseResponse([], 503));

    await expect(
      streamChat({
        fetchFn,
        apiBase: "http://api.test",
        query: "hi",
        history: [],
        onToken: () => undefined,
      }),
    ).rejects.toThrow("HTTP 503");
  });

  it("錯誤事件轉為例外", async () => {
    const fetchFn: FetchLike = vi.fn(async () =>
      sseResponse([frames({ token: "部分" }, { error: "AI 服務暫時無法使用" })]),
    );

    await expect(
      streamChat({
        fetchFn,
        apiBase: "http://api.test",
        query: "hi",
        history: [],
        onToken: () => undefined,
      }),
    ).rejects.toThrow("AI 服務暫時無法使用");
  });
});
