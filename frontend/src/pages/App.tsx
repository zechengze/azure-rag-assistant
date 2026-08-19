import { type JSX, useCallback, useEffect, useRef, useState } from "react";

import { ChatInterface } from "../components/ChatInterface";
import { DocumentList } from "../components/DocumentList";
import { DocumentUpload } from "../components/DocumentUpload";
import { useAuth } from "../hooks/useAuth";
import { useDocuments } from "../hooks/useDocuments";
import { useNavDrawer } from "../hooks/useNavDrawer";

const DRAWER_ID = "knowledge-drawer";

export function App(): JSX.Element {
  const auth = useAuth();
  const docs = useDocuments(auth.authFetch, auth.isAuthenticated);
  const { reload, deleteDocument } = docs;
  const nav = useNavDrawer();

  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const wasOpen = useRef(false);

  // 抽屜開啟時背景整塊 inert,原本聚焦的元素會失去焦點,因此需手動搬移:
  // 開啟 → 抽屜關閉鈕,關閉 → 回到漢堡鈕。
  useEffect(() => {
    if (nav.isOpen) {
      closeButtonRef.current?.focus();
    } else if (wasOpen.current) {
      menuButtonRef.current?.focus();
    }
    wasOpen.current = nav.isOpen;
  }, [nav.isOpen]);

  // 上傳成功後重新拉取清單,確保取得後端產生的 file_size / created_at。
  // 此處不關閉抽屜 —— 讓使用者看見新文件出現在清單裡。
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
    <div className="flex h-dvh">
      {/* 抽屜遮罩 —— 僅存在於手機版 */}
      {nav.isOpen && (
        <div
          onClick={nav.close}
          aria-hidden="true"
          className="fixed inset-0 z-30 bg-black/40 md:hidden"
        />
      )}

      {/* Sidebar: document list。<md 為滑出式抽屜,≥md 為常駐側欄。
          md:shrink-0 是必要的 —— 否則側欄會被聊天區的 min-content 擠壓變形。
          translate 只移出視覺不移出 a11y tree,故關閉時另以 invisible 移出 Tab 順序;
          這裡刻意用 CSS 而非 inert —— inert 得靠 JS 判斷斷點,一旦 media query 事件
          沒送達就會把桌面版側欄整塊鎖死,用 md:visible 則不可能有這種失效模式。 */}
      <aside
        id={DRAWER_ID}
        role={nav.isDesktop ? undefined : "dialog"}
        aria-modal={nav.isDesktop ? undefined : true}
        aria-label="知識庫"
        className={`fixed inset-y-0 left-0 z-40 flex w-72 max-w-[80vw] flex-col border-r border-gray-200 bg-white transition-[transform,visibility] duration-200 md:static md:visible md:z-auto md:max-w-none md:translate-x-0 md:shrink-0 ${
          nav.isOpen ? "visible translate-x-0" : "invisible -translate-x-full"
        }`}
      >
        <header className="flex items-center justify-between border-b border-gray-200 px-4 pb-3 pt-[calc(0.75rem+env(safe-area-inset-top))]">
          <h1 className="text-sm font-semibold text-gray-800">知識庫</h1>
          <button
            ref={closeButtonRef}
            onClick={nav.close}
            aria-label="關閉知識庫"
            className="-mr-2 flex h-11 w-11 items-center justify-center rounded text-gray-500 hover:bg-gray-100 md:hidden"
          >
            <CloseIcon />
          </button>
          <button
            onClick={auth.logout}
            className="-mr-1.5 hidden rounded px-1.5 py-1.5 text-xs text-gray-500 hover:bg-gray-100 hover:text-gray-700 md:block"
          >
            登出
          </button>
        </header>
        <DocumentUpload
          accessToken={auth.accessToken}
          refresh={auth.refresh}
          onUploaded={onUploaded}
        />
        <div className="flex-1 overflow-y-auto overscroll-contain px-2 pt-2 pb-[calc(0.5rem+env(safe-area-inset-bottom))]">
          <DocumentList
            documents={docs.documents}
            isLoading={docs.isLoading}
            error={docs.error}
            deletingId={docs.deletingId}
            onDelete={onDelete}
          />
        </div>
      </aside>

      {/* min-w-0 讓聊天區可以縮到比自身 min-content 更窄,避免反過來擠壓側欄 */}
      <div className="flex min-w-0 flex-1 flex-col" inert={!nav.isDesktop && nav.isOpen}>
        {/* 手機版頂部列 —— 抽屜關閉時,這是知識庫與登出的唯一入口 */}
        <header className="flex items-center gap-1 border-b border-gray-200 bg-white px-2 pb-2 pt-[calc(0.5rem+env(safe-area-inset-top))] md:hidden">
          <button
            ref={menuButtonRef}
            onClick={nav.open}
            aria-label="開啟知識庫"
            aria-expanded={nav.isOpen}
            aria-controls={DRAWER_ID}
            className="flex h-11 w-11 items-center justify-center rounded text-gray-600 hover:bg-gray-100"
          >
            <MenuIcon />
          </button>
          <h1 className="min-w-0 flex-1 truncate text-sm font-semibold text-gray-800">
            Azure RAG 知識問答助理
          </h1>
          <button
            onClick={auth.logout}
            className="flex h-11 items-center rounded px-3 text-xs text-gray-500 hover:bg-gray-100"
          >
            登出
          </button>
        </header>

        {/* min-h-0 讓 ChatInterface 內部的 overflow-y-auto 生效 */}
        <main className="min-h-0 flex-1 bg-gray-50">
          <ChatInterface authFetch={auth.authFetch} />
        </main>
      </div>
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
    <div className="flex h-dvh items-center justify-center bg-gray-50 px-4">
      <form
        onSubmit={submit}
        className="w-full max-w-xs bg-white rounded-lg shadow p-6 space-y-4"
      >
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
            className="w-full rounded border border-gray-300 px-3 py-2 text-base focus:outline-none focus:ring-2 focus:ring-blue-500 md:text-sm"
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
            className="w-full rounded border border-gray-300 px-3 py-2 text-base focus:outline-none focus:ring-2 focus:ring-blue-500 md:text-sm"
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

function MenuIcon(): JSX.Element {
  return (
    <svg
      className="h-5 w-5"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M4 7h16M4 12h16M4 17h16" />
    </svg>
  );
}

function CloseIcon(): JSX.Element {
  return (
    <svg
      className="h-5 w-5"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M6 6l12 12M18 6L6 18" />
    </svg>
  );
}
