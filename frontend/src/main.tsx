import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./pages/App";
import "./index.css";

const rootEl = document.getElementById("root");
if (!rootEl) {
  throw new Error("找不到 root 元素 — 確認 index.html 包含 <div id='root'>");
}

createRoot(rootEl).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
