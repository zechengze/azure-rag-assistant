/**
 * 文件上傳 —— 用 XMLHttpRequest 而非 fetch,因為只有前者能回報上傳進度。
 *
 * 也因為不是 fetch,無法沿用 useAuth 的 authFetch,401 後的 token 更新
 * 必須在這裡自己處理:access token 只有 60 分鐘,訪客把分頁放著一小時
 * 再上傳就會撞到 401。
 */

export interface UploadedDocument {
  document_id: string;
  title: string;
  chunk_count: number;
  message: string;
}

export interface UploadDocumentOptions {
  apiBase: string;
  file: File;
  title: string;
  accessToken: string | null;
  /** 取得新的 access token;回傳 null 代表 refresh token 也失效了。 */
  refresh: () => Promise<string | null>;
  onProgress?: (percent: number) => void;
}

interface XhrResult {
  status: number;
  body: string;
}

/**
 * 上傳單一文件。401 時以更新後的 token 重試一次。
 *
 * @throws Error 網路錯誤、非 201 回應,或回應無法解析
 */
export async function uploadDocument({
  apiBase,
  file,
  title,
  accessToken,
  refresh,
  onProgress,
}: UploadDocumentOptions): Promise<UploadedDocument> {
  const url = `${apiBase}/api/documents/upload/`;
  const send = (token: string | null): Promise<XhrResult> => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("title", title);
    return sendFormData(url, formData, token, onProgress);
  };

  let result = await send(accessToken);

  if (result.status === 401) {
    const renewed = await refresh();
    if (renewed !== null) {
      result = await send(renewed);
    }
  }

  if (result.status !== 201) {
    throw new Error(`上傳失敗 (HTTP ${result.status})`);
  }

  try {
    return JSON.parse(result.body) as UploadedDocument;
  } catch {
    throw new Error("回應解析失敗");
  }
}

function sendFormData(
  url: string,
  formData: FormData,
  token: string | null,
  onProgress?: (percent: number) => void,
): Promise<XhrResult> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();

    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable && onProgress !== undefined) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    });
    xhr.addEventListener("load", () => {
      resolve({ status: xhr.status, body: xhr.responseText });
    });
    xhr.addEventListener("error", () => {
      reject(new Error("網路錯誤"));
    });

    xhr.open("POST", url);
    // 不設 Content-Type:交給瀏覽器帶上 multipart 的 boundary。
    if (token !== null) {
      xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    }
    xhr.send(formData);
  });
}
