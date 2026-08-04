import { type JSX, useCallback } from "react";

import { DocumentItem } from "../hooks/useDocuments";

interface DocumentListProps {
  documents: DocumentItem[];
  isLoading: boolean;
  error: string | null;
  deletingId: string | null;
  onDelete: (documentId: string) => void;
}

/**
 * 側邊欄知識庫文件清單,每筆提供刪除操作。
 * 刪除為不可復原動作 (同時移除 Blob 與搜尋索引),故送出前需二次確認。
 */
export function DocumentList({
  documents,
  isLoading,
  error,
  deletingId,
  onDelete,
}: DocumentListProps): JSX.Element {
  const confirmDelete = useCallback(
    (doc: DocumentItem): void => {
      const ok = window.confirm(
        `確定要刪除「${doc.title}」嗎?\n此操作將一併移除搜尋索引,且無法復原。`,
      );
      if (ok) {
        onDelete(doc.document_id);
      }
    },
    [onDelete],
  );

  if (isLoading && documents.length === 0) {
    return <p className="mt-4 text-center text-xs text-gray-400">載入中...</p>;
  }

  return (
    <>
      {error !== null && (
        <p className="mx-2 mb-2 rounded bg-red-50 px-2 py-1 text-xs text-red-600">
          {error}
        </p>
      )}

      {documents.length === 0 ? (
        <p className="mt-4 text-center text-xs text-gray-400">尚未上傳文件</p>
      ) : (
        <ul className="space-y-1">
          {documents.map((doc) => {
            const isDeleting = deletingId === doc.document_id;
            return (
              <li
                key={doc.document_id}
                className="group flex items-start gap-2 rounded px-3 py-2 text-sm text-gray-700 hover:bg-gray-100"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium" title={doc.title}>
                    {doc.title}
                  </p>
                  <p className="text-xs text-gray-400">
                    {doc.chunk_count} 個段落 · {formatFileSize(doc.file_size)}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => confirmDelete(doc)}
                  disabled={isDeleting}
                  aria-label={`刪除 ${doc.title}`}
                  title="刪除"
                  className="shrink-0 rounded p-1 text-gray-400 opacity-0 transition hover:bg-red-50 hover:text-red-600 focus:opacity-100 focus:outline-none focus:ring-2 focus:ring-red-400 group-hover:opacity-100 disabled:cursor-not-allowed disabled:opacity-100"
                >
                  {isDeleting ? <SpinnerIcon /> : <TrashIcon />}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function TrashIcon(): JSX.Element {
  return (
    <svg
      className="h-4 w-4"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M6 7h12M10 11v6M14 11v6M5 7l1 12a2 2 0 002 2h8a2 2 0 002-2l1-12M9 7V5a1 1 0 011-1h4a1 1 0 011 1v2"
      />
    </svg>
  );
}

function SpinnerIcon(): JSX.Element {
  return (
    <svg
      className="h-4 w-4 animate-spin text-gray-500"
      fill="none"
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
      />
    </svg>
  );
}
