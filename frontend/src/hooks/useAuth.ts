import { useCallback, useEffect, useState } from "react";

const API_BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const ACCESS_KEY = "access_token";
const REFRESH_KEY = "refresh_token";

interface AuthState {
  accessToken: string | null;
  isAuthenticated: boolean;
}

interface TokenPair {
  access: string;
  refresh: string;
}

interface UseAuthReturn extends AuthState {
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  refresh: () => Promise<string | null>;
  authFetch: (input: RequestInfo, init?: RequestInit) => Promise<Response>;
}

/**
 * JWT 認證 Hook —— 提供 login / logout / refresh,以及自動帶入 Bearer Token 的 fetch wrapper。
 * Token 儲存在 localStorage,refresh token 失效時自動登出。
 */
export function useAuth(): UseAuthReturn {
  const [state, setState] = useState<AuthState>(() => {
    const token = localStorage.getItem(ACCESS_KEY);
    return { accessToken: token, isAuthenticated: token !== null };
  });

  useEffect(() => {
    const onStorage = (e: StorageEvent): void => {
      if (e.key === ACCESS_KEY) {
        setState({
          accessToken: e.newValue,
          isAuthenticated: e.newValue !== null,
        });
      }
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const login = useCallback(
    async (username: string, password: string): Promise<void> => {
      const resp = await fetch(`${API_BASE}/api/token/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (!resp.ok) {
        throw new Error(`登入失敗 (HTTP ${resp.status})`);
      }
      const data = (await resp.json()) as TokenPair;
      localStorage.setItem(ACCESS_KEY, data.access);
      localStorage.setItem(REFRESH_KEY, data.refresh);
      setState({ accessToken: data.access, isAuthenticated: true });
    },
    [],
  );

  const logout = useCallback((): void => {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
    setState({ accessToken: null, isAuthenticated: false });
  }, []);

  const refresh = useCallback(async (): Promise<string | null> => {
    const refreshToken = localStorage.getItem(REFRESH_KEY);
    if (refreshToken === null) {
      return null;
    }
    const resp = await fetch(`${API_BASE}/api/token/refresh/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh: refreshToken }),
    });
    if (!resp.ok) {
      logout();
      return null;
    }
    const data = (await resp.json()) as { access: string };
    localStorage.setItem(ACCESS_KEY, data.access);
    setState({ accessToken: data.access, isAuthenticated: true });
    return data.access;
  }, [logout]);

  /**
   * fetch wrapper:自動帶入 Authorization header,並在 401 時嘗試 refresh 後重試一次。
   */
  const authFetch = useCallback(
    async (input: RequestInfo, init: RequestInit = {}): Promise<Response> => {
      const buildHeaders = (token: string | null): Headers => {
        const headers = new Headers(init.headers);
        if (token !== null) {
          headers.set("Authorization", `Bearer ${token}`);
        }
        return headers;
      };

      let token = localStorage.getItem(ACCESS_KEY);
      let resp = await fetch(input, { ...init, headers: buildHeaders(token) });

      if (resp.status === 401) {
        token = await refresh();
        if (token !== null) {
          resp = await fetch(input, { ...init, headers: buildHeaders(token) });
        }
      }
      return resp;
    },
    [refresh],
  );

  return { ...state, login, logout, refresh, authFetch };
}
