import { type JSX, useCallback, useState } from "react";

import { ChatInterface } from "../components/ChatInterface";
import { DocumentList } from "../components/DocumentList";
import { DocumentUpload } from "../components/DocumentUpload";
import { useAuth } from "../hooks/useAuth";
import { useDocuments } from "../hooks/useDocuments";

export function App(): JSX.Element {
  const auth = useAuth();
  const docs = useDocuments(auth.authFetch, auth.isAuthenticated);
  const { reload, deleteDocument } = docs;

  // 上傳成功後重新拉取清單,確保取得後端產生的 file_size / created_at。
  const onUploaded = useCallback((): void => {
    void reload();
  }, [reload]);

  const onDelete = useCallback(
    (documentId: string): void => {
      void deleteDocument(documentId);
    },
    [deleteDocument],
  );

  if (!auth.isAuthenticated) {
    return <LoginForm onLogin={auth.login} />;
  }

  return (
    <div className="flex h-screen">
      {/* Sidebar: document list */}
      <aside className="w-72 border-r border-gray-200 bg-white flex flex-col">
        <header className="px-4 py-3 border-b border-gray-200 flex items-center justify-between">
          <h1 className="text-sm font-semibold text-gray-800">知識庫</h1>
          <button
            onClick={auth.logout}
            className="text-xs text-gray-500 hover:text-gray-700"
          >
            登出
          </button>
        </header>
        <DocumentUpload
          accessToken={auth.accessToken}
          refresh={auth.refresh}
          onUploaded={onUploaded}
        />
        <div className="flex-1 overflow-y-auto px-2 py-2">
          <DocumentList
            documents={docs.documents}
            isLoading={docs.isLoading}
            error={docs.error}
            deletingId={docs.deletingId}
            onDelete={onDelete}
          />
        </div>
      </aside>

      {/* Main: chat */}
      <main className="flex-1 bg-gray-50">
        <ChatInterface authFetch={auth.authFetch} />
      </main>
    </div>
  );
}

interface LoginFormProps {
  onLogin: (username: string, password: string) => Promise<void>;
}

function LoginForm({ onLogin }: LoginFormProps): JSX.Element {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const submit = useCallback(
    async (e: React.FormEvent<HTMLFormElement>): Promise<void> => {
      e.preventDefault();
      setError(null);
      setSubmitting(true);
      try {
        await onLogin(username, password);
      } catch (err) {
        setError(err instanceof Error ? err.message : "登入失敗");
      } finally {
        setSubmitting(false);
      }
    },
    [username, password, onLogin],
  );

  return (
    <div className="flex h-screen items-center justify-center bg-gray-50">
      <form onSubmit={submit} className="w-80 bg-white rounded-lg shadow p-6 space-y-4">
        <h1 className="text-lg font-semibold text-gray-800">
          Azure RAG Knowledge Assistant
        </h1>
        <div>
          <label className="block text-xs text-gray-500 mb-1" htmlFor="username">
            帳號
          </label>
          <input
            id="username"
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            required
          />
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1" htmlFor="password">
            密碼
          </label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            required
          />
        </div>
        {error !== null && <p className="text-sm text-red-600">{error}</p>}
        <button
          type="submit"
          disabled={submitting}
          className="w-full bg-blue-600 text-white text-sm font-medium py-2 rounded hover:bg-blue-700 disabled:opacity-50"
        >
          {submitting ? "登入中..." : "登入"}
        </button>
      </form>
    </div>
  );
}
