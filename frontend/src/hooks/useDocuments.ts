import { useCallback, useEffect, useState } from "react";

const API_BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export interface DocumentItem {
  document_id: string;
  title: string;
  chunk_count: number;
  file_size: number;
  created_at: string;
}

type AuthFetch = (input: RequestInfo, init?: RequestInit) => Promise<Response>;

interface UseDocumentsReturn {
  documents: DocumentItem[];
  isLoading: boolean;
  error: string | null;
  deletingId: string | null;
  reload: () => Promise<void>;
  deleteDocument: (documentId: string) => Promise<void>;
}

/**
 * 知識庫文件 Hook —— 載入使用者的文件清單,並提供刪除操作。
 * 刪除成功後同步移除本地狀態,失敗則保留該筆並回報錯誤訊息。
 *
 * @param authFetch 帶 JWT 的 fetch wrapper (來自 useAuth)
 * @param enabled   為 false 時不發送請求 (例如尚未登入)
 */
export function useDocuments(
  authFetch: AuthFetch,
  enabled: boolean,
): UseDocumentsReturn {
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const reload = useCallback(async (): Promise<void> => {
    setIsLoading(true);
    setError(null);
    try {
      const resp = await authFetch(`${API_BASE}/api/documents/`);
      if (!resp.ok) {
        throw new Error(`文件清單載入失敗 (HTTP ${resp.status})`);
      }
      const data = (await resp.json()) as { documents: DocumentItem[] };
      setDocuments(data.documents);
    } catch (err) {
      setError(err instanceof Error ? err.message : "文件清單載入失敗");
    } finally {
      setIsLoading(false);
    }
  }, [authFetch]);

  useEffect(() => {
    if (!enabled) {
      // 此處刻意不改用「回傳時依 enabled 推導」的寫法。推導雖然能移除這次
      // setState,但 state 會留著上一個帳號的清單:下一位使用者登入後,在
      // reload() 完成前 (一個網路往返) 會渲染前一位的文件標題,而
      // DocumentList 的 `isLoading && documents.length === 0` 判斷還會讓它
      // 跳過「載入中」直接顯示。
      //
      // 真正的推導解法需要 session 識別,但 access token 會在 refresh 時輪替,
      // 拿它當 key 會讓清單無故清空;登出也有不經過按鈕的自動路徑
      // (useAuth 於 refresh 失敗時),所以「在 handler 清空」同樣蓋不全。
      // eslint-disable-next-line react-hooks/set-state-in-effect -- 清除跨帳號殘留優先於避免一次連鎖 render
      setDocuments([]);
      return;
    }
    void reload();
  }, [enabled, reload]);

  const deleteDocument = useCallback(
    async (documentId: string): Promise<void> => {
      setDeletingId(documentId);
      setError(null);
      try {
        const resp = await authFetch(
          `${API_BASE}/api/documents/${encodeURIComponent(documentId)}/`,
          { method: "DELETE" },
        );
        if (resp.status === 404) {
          throw new Error("文件不存在或已被刪除");
        }
        if (resp.status !== 204) {
          throw new Error(`刪除失敗 (HTTP ${resp.status})`);
        }
        setDocuments((prev) =>
          prev.filter((doc) => doc.document_id !== documentId),
        );
      } catch (err) {
        setError(err instanceof Error ? err.message : "文件刪除失敗");
      } finally {
        setDeletingId(null);
      }
    },
    [authFetch],
  );

  return { documents, isLoading, error, deletingId, reload, deleteDocument };
}
