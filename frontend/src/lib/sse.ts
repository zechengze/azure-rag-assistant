/**
 * Server-Sent Events 解析 —— 後端 /api/chat/ 串流的接收端。
 *
 * 兩件事必須照規範做,少一件就會掉字:
 *   1. 事件由「空行」界定,不是由網路封包界定。reader.read() 拿到的區塊
 *      可能切在事件中間,未收完的尾巴要留在 buffer 等下一個區塊。
 *   2. 一個事件可以有多行 `data:`,接收端以換行接回。
 *
 * 後端每個事件都是單行 JSON (見 api/views.py 的 sse_event),token 內含的
 * 換行已在序列化時轉義,因此不會與事件邊界混淆。
 */

export type ChatStreamEvent =
  | { type: "token"; value: string }
  | { type: "done" }
  | { type: "error"; message: string };

interface EventPayload {
  token?: unknown;
  done?: unknown;
  error?: unknown;
}

/**
 * 建立增量式解析器:逐段餵入解碼後的文字,回傳這段湊齊的事件。
 * 解析器持有跨區塊的 buffer,故每個串流需各自建立一個。
 */
export function createSSEParser(): (chunk: string) => ChatStreamEvent[] {
  let buffer = "";

  return (chunk: string): ChatStreamEvent[] => {
    buffer += chunk;
    const events: ChatStreamEvent[] = [];

    for (;;) {
      const boundary = buffer.indexOf("\n\n");
      if (boundary === -1) {
        break;
      }
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);

      const event = parseBlock(block);
      if (event !== null) {
        events.push(event);
      }
    }

    return events;
  };
}

function parseBlock(block: string): ChatStreamEvent | null {
  const dataLines: string[] = [];
  for (const rawLine of block.split("\n")) {
    // 容忍 CRLF;以 ":" 開頭的註解行與其他欄位 (event/id/retry) 一律略過。
    const line = rawLine.endsWith("\r") ? rawLine.slice(0, -1) : rawLine;
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).replace(/^ /, ""));
    }
  }
  if (dataLines.length === 0) {
    return null;
  }

  let payload: EventPayload;
  try {
    payload = JSON.parse(dataLines.join("\n")) as EventPayload;
  } catch {
    // 半途中斷的串流可能留下不完整的 JSON,略過該事件而非讓整個回答失敗。
    return null;
  }

  if (typeof payload.error === "string") {
    return { type: "error", message: payload.error };
  }
  if (payload.done === true) {
    return { type: "done" };
  }
  if (typeof payload.token === "string") {
    return { type: "token", value: payload.token };
  }
  return null;
}
