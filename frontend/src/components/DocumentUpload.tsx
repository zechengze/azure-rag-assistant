import { type JSX, ChangeEvent, DragEvent, useCallback, useRef, useState } from "react";

import { uploadDocument, type UploadedDocument } from "../lib/upload";

const API_BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const MAX_SIZE_MB = 10;

const ALLOWED_MIME = new Set<string>([
  "application/pdf",
  "text/plain",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
]);

export type { UploadedDocument };

interface DocumentUploadProps {
  /** 目前的 access token 與更新函式,皆來自 useAuth。 */
  accessToken: string | null;
  refresh: () => Promise<string | null>;
  onUploaded?: (doc: UploadedDocument) => void;
}

interface UploadState {
  isDragging: boolean;
  isUploading: boolean;
  progress: number;
  error: string | null;
}

export function DocumentUpload({
  accessToken,
  refresh,
  onUploaded,
}: DocumentUploadProps): JSX.Element {
  const [state, setState] = useState<UploadState>({
    isDragging: false,
    isUploading: false,
    progress: 0,
    error: null,
  });
  const inputRef = useRef<HTMLInputElement>(null);

  const uploadFile = useCallback(
    async (file: File): Promise<void> => {
      setState({ isDragging: false, isUploading: false, progress: 0, error: null });

      if (!ALLOWED_MIME.has(file.type)) {
        setState((s) => ({ ...s, error: "僅支援 PDF / TXT / DOCX" }));
        return;
      }
      if (file.size > MAX_SIZE_MB * 1024 * 1024) {
        setState((s) => ({ ...s, error: `檔案大小不得超過 ${MAX_SIZE_MB} MB` }));
        return;
      }

      setState((s) => ({ ...s, isUploading: true, progress: 0 }));

      try {
        const doc = await uploadDocument({
          apiBase: API_BASE,
          file,
          title: file.name,
          accessToken,
          refresh,
          onProgress: (percent) => setState((s) => ({ ...s, progress: percent })),
        });
        setState({
          isDragging: false,
          isUploading: false,
          progress: 100,
          error: null,
        });
        onUploaded?.(doc);
      } catch (err) {
        setState((s) => ({
          ...s,
          isUploading: false,
          error: err instanceof Error ? err.message : "上傳失敗",
        }));
      }
    },
    [accessToken, refresh, onUploaded],
  );

  const onFileChange = useCallback(
    (e: ChangeEvent<HTMLInputElement>): void => {
      const file = e.target.files?.[0];
      if (file !== undefined) {
        void uploadFile(file);
      }
      e.target.value = "";
    },
    [uploadFile],
  );

  const onDragOver = useCallback((e: DragEvent<HTMLDivElement>): void => {
    e.preventDefault();
    setState((s) => ({ ...s, isDragging: true }));
  }, []);

  const onDragLeave = useCallback((e: DragEvent<HTMLDivElement>): void => {
    e.preventDefault();
    setState((s) => ({ ...s, isDragging: false }));
  }, []);

  const onDrop = useCallback(
    (e: DragEvent<HTMLDivElement>): void => {
      e.preventDefault();
      setState((s) => ({ ...s, isDragging: false }));
      const file = e.dataTransfer.files?.[0];
      if (file !== undefined) {
        void uploadFile(file);
      }
    },
    [uploadFile],
  );

  return (
    <div className="p-4">
      <div
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        className={`cursor-pointer rounded-lg border-2 border-dashed p-6 text-center transition-colors ${
          state.isDragging
            ? "border-blue-500 bg-blue-50"
            : "border-gray-300 bg-white hover:border-gray-400"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.txt,.docx"
          className="hidden"
          onChange={onFileChange}
          disabled={state.isUploading}
        />
        <p className="text-sm text-gray-600">
          {state.isUploading ? (
            `上傳中 ${state.progress}%`
          ) : (
            <>
              {/* 觸控裝置沒有拖放,依指標能力切換文案而非螢幕寬度 */}
              <span className="can-hover:hidden">點擊選擇檔案</span>
              <span className="hidden can-hover:inline">拖放檔案至此或點擊上傳</span>
            </>
          )}
        </p>
        <p className="text-xs text-gray-400 mt-1">
          支援 PDF / TXT / DOCX,最大 {MAX_SIZE_MB} MB
        </p>
      </div>

      {state.isUploading && (
        <div className="mt-2 h-1 w-full bg-gray-200 rounded">
          <div
            className="h-full bg-blue-600 rounded transition-all"
            style={{ width: `${state.progress}%` }}
          />
        </div>
      )}

      {state.error !== null && (
        <p className="mt-2 text-sm text-red-600">{state.error}</p>
      )}
    </div>
  );
}
