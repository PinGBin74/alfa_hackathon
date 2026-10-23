import { useCallback, useEffect, useRef, useState } from "react";

const TOKEN_KEY = "ani.token";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* приватный режим: токен живёт до перезагрузки страницы */
  }
}

// Понятные сообщения для кодов, которые backend отдаёт осознанно
const STATUS_TEXT: Record<number, string> = {
  401: "Сессия истекла: войдите заново.",
  403: "Нет доступа к этой компании.",
  404: "Не найдено.",
  422: "Запрос не принят.",
  429: "Дневной лимит запросов к моделям исчерпан. Готовые разборы по-прежнему доступны.",
  502: "Языковые модели сейчас недоступны. Повторите через минуту.",
  504: "Разбор готовится слишком долго. Повторите позже.",
};

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  let resp: Response;
  try {
    resp = await fetch(`/api${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "Сервер недоступен. Проверьте, что backend запущен.");
  }
  if (!resp.ok) {
    let detail = "";
    try {
      const body = await resp.json();
      detail = typeof body.detail === "string" ? body.detail : "";
    } catch {
      /* не JSON */
    }
    if (resp.status === 401) setToken(null);
    const known = STATUS_TEXT[resp.status];
    throw new ApiError(resp.status, resp.status === 422 && detail ? detail : known ?? (detail || `Ошибка ${resp.status}`));
  }
  if (resp.status === 204) return undefined as T;
  const type = resp.headers.get("Content-Type") ?? "";
  return (type.includes("application/json") ? resp.json() : resp.blob()) as Promise<T>;
}

export const post = <T,>(path: string, body?: unknown) =>
  api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

/** Загрузка по пути; path = null - не загружать. */
export function useApi<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(Boolean(path));
  const seq = useRef(0);

  const load = useCallback(() => {
    if (!path) return;
    const id = ++seq.current;
    setLoading(true);
    setError(null);
    api<T>(path)
      .then((d) => id === seq.current && setData(d))
      .catch((e: ApiError) => id === seq.current && setError(e))
      .finally(() => id === seq.current && setLoading(false));
  }, [path]);

  useEffect(() => {
    setData(null);
    load();
  }, [load]);

  return { data, error, loading, reload: load, setData };
}
