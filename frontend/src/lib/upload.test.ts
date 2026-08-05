import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { uploadDocument } from "./upload";

interface ScriptedResponse {
  status: number;
  body?: string;
  networkError?: boolean;
}

interface RecordedRequest {
  url: string;
  headers: Record<string, string>;
  body: FormData;
}

const scripted: ScriptedResponse[] = [];
const requests: RecordedRequest[] = [];

/** 最小可用的 XMLHttpRequest 替身:依 scripted 佇列逐一回應。 */
class FakeXHR {
  status = 0;
  responseText = "";
  private url = "";
  private headers: Record<string, string> = {};
  private listeners: Record<string, (e?: unknown) => void> = {};
  private progressListener?: (e: unknown) => void;

  upload = {
    addEventListener: (_type: string, cb: (e: unknown) => void): void => {
      this.progressListener = cb;
    },
  };

  open(_method: string, url: string): void {
    this.url = url;
  }

  setRequestHeader(key: string, value: string): void {
    this.headers[key] = value;
  }

  addEventListener(type: string, cb: (e?: unknown) => void): void {
    this.listeners[type] = cb;
  }

  send(body: FormData): void {
    requests.push({ url: this.url, headers: this.headers, body });
    const next = scripted.shift();
    queueMicrotask(() => {
      this.progressListener?.({ lengthComputable: true, loaded: 5, total: 10 });
      if (next === undefined || next.networkError === true) {
        this.listeners.error?.();
        return;
      }
      this.status = next.status;
      this.responseText = next.body ?? "";
      this.listeners.load?.();
    });
  }
}

const created = JSON.stringify({
  document_id: "abc",
  title: "a.txt",
  chunk_count: 3,
  message: "ok",
});

function options(overrides: Partial<Parameters<typeof uploadDocument>[0]> = {}) {
  return {
    apiBase: "http://api.test",
    file: new File(["hello"], "a.txt", { type: "text/plain" }),
    title: "a.txt",
    accessToken: "old-token",
    refresh: vi.fn(async () => null),
    ...overrides,
  };
}

beforeEach(() => {
  scripted.length = 0;
  requests.length = 0;
  vi.stubGlobal("XMLHttpRequest", FakeXHR);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("uploadDocument", () => {
  it("成功時回傳後端建立的文件並帶上 Bearer token", async () => {
    scripted.push({ status: 201, body: created });

    const doc = await uploadDocument(options());

    expect(doc.document_id).toBe("abc");
    expect(requests).toHaveLength(1);
    expect(requests[0].url).toBe("http://api.test/api/documents/upload/");
    expect(requests[0].headers.Authorization).toBe("Bearer old-token");
  });

  it("token 過期時更新後重試一次", async () => {
    // access token 只有 60 分鐘;沒有這段重試,分頁放久一點再上傳就直接失敗。
    scripted.push({ status: 401 }, { status: 201, body: created });
    const refresh = vi.fn(async () => "new-token");

    const doc = await uploadDocument(options({ refresh }));

    expect(doc.document_id).toBe("abc");
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(requests).toHaveLength(2);
    expect(requests[1].headers.Authorization).toBe("Bearer new-token");
  });

  it("refresh token 也失效時不再重試,回報 401", async () => {
    scripted.push({ status: 401 });
    const refresh = vi.fn(async () => null);

    await expect(uploadDocument(options({ refresh }))).rejects.toThrow("HTTP 401");
    expect(requests).toHaveLength(1);
  });

  it("回報上傳進度", async () => {
    scripted.push({ status: 201, body: created });
    const onProgress = vi.fn();

    await uploadDocument(options({ onProgress }));

    expect(onProgress).toHaveBeenCalledWith(50);
  });

  it("網路錯誤時拋出", async () => {
    scripted.push({ networkError: true, status: 0 });

    await expect(uploadDocument(options())).rejects.toThrow("網路錯誤");
  });

  it("回應非 JSON 時拋出", async () => {
    scripted.push({ status: 201, body: "<html>proxy error</html>" });

    await expect(uploadDocument(options())).rejects.toThrow("回應解析失敗");
  });
});
