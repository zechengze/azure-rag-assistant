import { ChangeEvent, DragEvent, useCallback, useRef, useState } from "react";

const API_BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const MAX_SIZE_MB = 10;

const ALLOWED_MIME = new Set<string>([
  "application/pdf",
  "text/plain",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
]);

export interface UploadedDocument {
  document_id: string;
  title: string;
  chunk_count: number;
  message: string;
}

interface DocumentUploadProps {
  onUploaded?: (doc: UploadedDocument) => void;
}

interface UploadState {
  isDragging: boolean;
  isUploading: boolean;
  progress: number;
  error: string | null;
}

export function DocumentUpload({ onUploaded }: DocumentUploadProps): JSX.Element {
  const [state, setState] = useState<UploadState>({
    isDragging: false,
    isUploading: false,
    progress: 0,
    error: null,
  });
  const inputRef = useRef<HTMLInputElement>(null);

  const uploadFile = useCallback(
    (file: File): void => {
      setState({ isDragging: false, isUploading: false, progress: 0, error: null });

      if (!ALLOWED_MIME.has(file.type)) {
        setState((s) => ({ ...s, error: "僅支援 PDF / TXT / DOCX" }));
        return;
      }
      if (file.size > MAX_SIZE_MB * 1024 * 1024) {
        setState((s) => ({ ...s, error: `檔案大小不得超過 ${MAX_SIZE_MB} MB` }));
        return;
      }

      const formData = new FormData();
      formData.append("file", file);
      formData.append("title", file.name);

      const xhr = new XMLHttpRequest();
      xhr.upload.addEventListener("progress", (e) => {
        if (e.lengthComputable) {
          const pct = Math.round((e.loaded / e.total) * 100);
          setState((s) => ({ ...s, progress: pct }));
        }
      });
      xhr.addEventListener("load", () => {
        if (xhr.status === 201) {
          try {
            const data = JSON.parse(xhr.responseText) as UploadedDocument;
            setState({
              isDragging: false,
              isUploading: false,
              progress: 100,
              error: null,
            });
            onUploaded?.(data);
          } catch {
            setState((s) => ({ ...s, isUploading: false, error: "回應解析失敗" }));
          }
        } else {
          setState((s) => ({
            ...s,
            isUploading: false,
            error: `上傳失敗 (HTTP ${xhr.status})`,
          }));
        }
      });
      xhr.addEventListener("error", () => {
        setState((s) => ({ ...s, isUploading: false, error: "網路錯誤" }));
      });

      const token = localStorage.getItem("access_token");
      xhr.open("POST", `${API_BASE}/api/documents/upload/`);
      if (token !== null) {
        xhr.setRequestHeader("Authorization", `Bearer ${token}`);
      }

      setState((s) => ({ ...s, isUploading: true, progress: 0 }));
      xhr.send(formData);
    },
    [onUploaded],
  );

  const onFileChange = useCallback(
    (e: ChangeEvent<HTMLInputElement>): void => {
      const file = e.target.files?.[0];
      if (file !== undefined) {
        uploadFile(file);
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
        uploadFile(file);
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
          {state.isUploading
            ? `上傳中 ${state.progress}%`
            : "拖放檔案至此或點擊上傳"}
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
