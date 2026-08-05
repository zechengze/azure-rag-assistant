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

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
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
      <div className="flex-1 overflow-y-auto px-4 py-6 space-y-4">
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
      <div className="border-t border-gray-200 px-4 py-3">
        <div className="flex items-end gap-3 max-w-3xl mx-auto">
          <textarea
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="輸入問題... (Enter 送出，Shift+Enter 換行)"
            className="flex-1 resize-none rounded-lg border border-gray-300 px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 max-h-32"
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
        <p className="text-xs text-gray-400 text-center mt-2">{query.length}/2000</p>
      </div>
    </div>
  );
}

function MessageBubble({ message }: { message: Message }): JSX.Element {
  const isUser = message.role === "user";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-2xl rounded-2xl px-4 py-3 text-sm leading-relaxed ${
          isUser
            ? "bg-blue-600 text-white rounded-br-md"
            : "bg-gray-100 text-gray-800 rounded-bl-md"
        }`}
      >
        <p className="whitespace-pre-wrap">{message.content}</p>

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
