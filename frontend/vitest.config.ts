import { defineConfig } from "vitest/config";

// 測試對象是 src/lib/ 底下與 UI 無關的純邏輯 (SSE 解析、請求組裝),
// 因此用 node 環境即可,不需要 jsdom。
export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
