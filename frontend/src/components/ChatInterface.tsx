import { type JSX, useState, useRef, useEffect, useCallback } from "react";

import { streamChat, type FetchLike } from "../lib/chat";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: { title: string; chunk_index: number }[];
  isStreaming?: boolean;
}

interface ChatState {
  messages: Message[];
  isLoading: boolean;
  error: string | null;
}

const API_BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

/** 距離底部在此範圍內才視為「正在追最新訊息」,超過代表使用者刻意往上捲。 */
const FOLLOW_BOTTOM_THRESHOLD_PX = 80;

interface ChatInterfaceProps {
  /** 來自 useAuth,負責帶上 JWT 並在 401 時更新 token 後重試。 */
  authFetch: FetchLike;
}

export function ChatInterface({ authFetch }: ChatInterfaceProps): JSX.Element {
  const [state, setState] = useState<ChatState>({
    messages: [],
    isLoading: false,
    error: null,
  });
  const [query, setQuery] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // 使用者往上捲看歷史時,不該被串流中的 token 一直拉回底部。
  const followBottomRef = useRef(true);

  const onListScroll = useCallback((e: React.UIEvent<HTMLDivElement>): void => {
    const el = e.currentTarget;
    followBottomRef.current =
      el.scrollHeight - el.scrollTop - el.clientHeight <= FOLLOW_BOTTOM_THRESHOLD_PX;
  }, []);

  useEffect(() => {
    if (!followBottomRef.current) {
      return;
    }
    // 串流期間每個 token 都會觸發此 effect,smooth 會不斷重啟動畫反而追不上,
    // 故串流時用瞬間捲動,訊息收完才用平滑捲動。
    const isStreaming = state.messages.at(-1)?.isStreaming === true;
    bottomRef.current?.scrollIntoView({ behavior: isStreaming ? "auto" : "smooth" });
  }, [state.messages]);

  const buildHistory = (messages: Message[]): { role: string; content: string }[] =>
    messages
      .filter((m) => !m.isStreaming)
      .map((m) => ({ role: m.role, content: m.content }));

  const sendMessage = useCallback(async () => {
    const trimmed = query.trim();
    if (!trimmed || state.isLoading) return;

    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: trimmed,
    };

    const assistantMessage: Message = {
      id: crypto.randomUUID(),
      role: "assistant",
      content: "",
      isStreaming: true,
    };

    // 送出新訊息代表使用者的注意力回到最新內容,不論先前捲到哪裡都跟回底部。
    followBottomRef.current = true;
    setState((prev) => ({
      ...prev,
      messages: [...prev.messages, userMessage, assistantMessage],
      isLoading: true,
      error: null,
    }));
    setQuery("");

    try {
      await streamChat({
        fetchFn: authFetch,
        apiBase: API_BASE,
        query: trimmed,
        history: buildHistory(state.messages),
        onToken: (accumulated) => {
          setState((prev) => ({
            ...prev,
            messages: prev.messages.map((m) =>
              m.id === assistantMessage.id ? { ...m, content: accumulated } : m,
            ),
          }));
        },
      });

      setState((prev) => ({
        ...prev,
        messages: prev.messages.map((m) =>
          m.id === assistantMessage.id ? { ...m, isStreaming: false } : m,
        ),
        isLoading: false,
      }));
    } catch (err) {
      setState((prev) => ({
        ...prev,
        messages: prev.messages.filter((m) => m.id !== assistantMessage.id),
        isLoading: false,
        error: err instanceof Error ? err.message : "請求失敗，請稍後再試",
      }));
    }
  }, [authFetch, query, state.isLoading, state.messages]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* 訊息列表 */}
      <div
        onScroll={onListScroll}
        className="flex-1 overflow-y-auto overscroll-contain px-4 py-6 space-y-4"
      >
        {state.messages.length === 0 && (
          <div className="text-center text-gray-400 mt-20">
            <p className="text-lg font-medium">Azure RAG 知識問答助理</p>
            <p className="text-sm mt-2">上傳文件後，即可開始詢問相關問題</p>
          </div>
        )}

        {state.messages.map((message) => (
          <MessageBubble key={message.id} message={message} />
        ))}

        {state.error && (
          <div className="text-red-500 text-sm text-center py-2">{state.error}</div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* 輸入區 */}
      <div className="border-t border-gray-200 px-4 pt-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))]">
        <div className="flex items-end gap-2 max-w-3xl mx-auto md:gap-3">
          <textarea
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="輸入問題..."
            className="min-w-0 flex-1 resize-none rounded-lg border border-gray-300 px-4 py-3 text-base focus:outline-none focus:ring-2 focus:ring-blue-500 max-h-32 md:text-sm"
            rows={1}
            maxLength={2000}
            disabled={state.isLoading}
          />
          <button
            onClick={sendMessage}
            disabled={state.isLoading || !query.trim()}
            className="px-4 py-3 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {state.isLoading ? "處理中..." : "送出"}
          </button>
        </div>
        <p className="text-xs text-gray-400 text-center mt-2">
          {/* 快捷鍵提示只對實體鍵盤有意義,手機版隱藏以免佔用寬度 */}
          <span className="hidden md:inline">Enter 送出，Shift+Enter 換行 · </span>
          {query.length}/2000
        </p>
      </div>
    </div>
  );
}

function MessageBubble({ message }: { message: Message }): JSX.Element {
  const isUser = message.role === "user";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed md:max-w-2xl ${
          isUser
            ? "bg-blue-600 text-white rounded-br-md"
            : "bg-gray-100 text-gray-800 rounded-bl-md"
        }`}
      >
        <p className="whitespace-pre-wrap break-words">{message.content}</p>

        {message.isStreaming && (
          <span className="inline-block w-1.5 h-4 bg-current ml-1 animate-pulse" />
        )}

        {message.sources && message.sources.length > 0 && !message.isStreaming && (
          <div className="mt-2 pt-2 border-t border-gray-300">
            <p className="text-xs text-gray-500 mb-1">參考來源：</p>
            {message.sources.map((source, i) => (
              <span
                key={i}
                className="inline-block text-xs bg-gray-200 text-gray-600 px-2 py-0.5 rounded mr-1 mb-1"
              >
                {source.title}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
