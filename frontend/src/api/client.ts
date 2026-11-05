// Minimal typed API client. The officer token lives in sessionStorage only (cleared on tab close/logout);
// responses are never persisted to localStorage or any offline cache.

const BASE = "/api/v1";
const TOKEN_KEY = "tsep.officer.token";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;

  constructor(status: number, code: string, message: string, details: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export const tokenStore = {
  get: (): string | null => sessionStorage.getItem(TOKEN_KEY),
  set: (t: string): void => sessionStorage.setItem(TOKEN_KEY, t),
  clear: (): void => sessionStorage.removeItem(TOKEN_KEY),
};

let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: () => void): void {
  onUnauthorized = fn;
}

function authHeaders(): Record<string, string> {
  const t = tokenStore.get();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

async function parseError(res: Response): Promise<ApiError> {
  let code = "HTTP_" + res.status;
  let message = res.statusText || "Request failed";
  let details: unknown = null;
  try {
    const body = (await res.json()) as { code?: string; message?: string; details?: unknown };
    code = body.code ?? code;
    message = body.message ?? message;
    details = body.details ?? null;
  } catch {
    /* non-JSON error body */
  }
  if (res.status === 401 && onUnauthorized) onUnauthorized();
  return new ApiError(res.status, code, message, details);
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...authHeaders(), ...(init.headers as Record<string, string>) };
  if (init.body && !(init.body instanceof FormData)) headers["Content-Type"] = "application/json";
  const res = await fetch(BASE + path, { ...init, headers, cache: "no-store", credentials: "omit" });
  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const get = <T>(path: string): Promise<T> => api<T>(path);
export const post = <T>(path: string, body?: unknown, headers?: Record<string, string>): Promise<T> =>
  api<T>(path, {
    method: "POST",
    body: body instanceof FormData ? body : JSON.stringify(body ?? {}),
    headers: headers ?? {},
  });
export const put = <T>(path: string, body: unknown): Promise<T> =>
  api<T>(path, { method: "PUT", body: JSON.stringify(body) });

/** Fetch a protected binary (page image / PDF) as an object URL. Caller must revoke it. */
export async function fetchBlobUrl(path: string): Promise<string> {
  const res = await fetch(BASE + path, { headers: authHeaders(), cache: "no-store", credentials: "omit" });
  if (!res.ok) throw await parseError(res);
  return URL.createObjectURL(await res.blob());
}

export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}
