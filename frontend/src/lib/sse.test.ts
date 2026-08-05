import { describe, expect, it } from "vitest";

import { createSSEParser } from "./sse";

describe("createSSEParser", () => {
  it("解析單一 token 事件", () => {
    const parse = createSSEParser();
    expect(parse('data: {"token":"Hello"}\n\n')).toEqual([
      { type: "token", value: "Hello" },
    ]);
  });

  it("還原 token 內含的換行", () => {
    const parse = createSSEParser();
    const events = parse('data: {"token":"第一行\\n\\n1. 項目一"}\n\n');
    expect(events).toEqual([{ type: "token", value: "第一行\n\n1. 項目一" }]);
  });

  it("事件被切在兩個網路區塊中間時仍完整還原", () => {
    const parse = createSSEParser();
    // reader.read() 依網路封包切分,與事件邊界無關。
    expect(parse('data: {"tok')).toEqual([]);
    expect(parse('en":"接續"}\n')).toEqual([]);
    expect(parse("\n")).toEqual([{ type: "token", value: "接續" }]);
  });

  it("一個區塊含多個事件時全部回傳", () => {
    const parse = createSSEParser();
    const events = parse('data: {"token":"a"}\n\ndata: {"token":"b"}\n\n');
    expect(events).toEqual([
      { type: "token", value: "a" },
      { type: "token", value: "b" },
    ]);
  });

  it("辨識結束與錯誤事件", () => {
    const parse = createSSEParser();
    expect(parse('data: {"done":true}\n\n')).toEqual([{ type: "done" }]);
    expect(parse('data: {"error":"服務暫時無法使用"}\n\n')).toEqual([
      { type: "error", message: "服務暫時無法使用" },
    ]);
  });

  it("token 內容剛好等於舊哨符時仍視為一般 token", () => {
    const parse = createSSEParser();
    expect(parse('data: {"token":"[DONE]"}\n\n')).toEqual([
      { type: "token", value: "[DONE]" },
    ]);
  });

  it("略過註解行、其他欄位與不完整的 JSON", () => {
    const parse = createSSEParser();
    expect(parse(': keep-alive\n\nevent: ping\n\ndata: {"tok\n\n')).toEqual([]);
  });

  it("接受多行 data 與 CRLF 換行", () => {
    const parse = createSSEParser();
    expect(parse('data: {"token":\r\ndata: "多行"}\r\n\n')).toEqual([
      { type: "token", value: "多行" },
    ]);
  });
});
