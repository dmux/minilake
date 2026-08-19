/**
 * Low-level HTTP client for the minilake API.
 *
 * In production the UI is served by minilake itself at /ui, so every request is
 * same-origin and needs no base URL. The env var exists for `pnpm dev`, where the
 * UI runs on :3000 and the API on :8000 — `output: "export"` forbids rewrites, so
 * an absolute base is the only way across (and the server needs MINILAKE_DEV_CORS=1).
 */
const API_BASE = (process.env.NEXT_PUBLIC_MINILAKE_API_BASE ?? "").replace(/\/$/, "");

/** A Databricks-shaped API error: `{error_code, message}` at a non-2xx status. */
export class MinilakeApiError extends Error {
  readonly status: number;
  readonly errorCode: string;

  constructor(status: number, errorCode: string, message: string) {
    super(message);
    this.name = "MinilakeApiError";
    this.status = status;
    this.errorCode = errorCode;
  }
}

export interface RequestOptions {
  method?: string;
  /** JSON body. Mutually exclusive with `raw`. */
  body?: unknown;
  /** Raw body for endpoints that take bytes rather than JSON (file uploads). */
  raw?: BodyInit;
  query?: Record<string, string | number | boolean | undefined | null>;
  signal?: AbortSignal;
  headers?: Record<string, string>;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = `${API_BASE}${path}`;
  if (!query) return url;

  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") {
      params.set(key, String(value));
    }
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

async function toApiError(response: Response): Promise<MinilakeApiError> {
  // Statement failures come back as an HTTP error body, not as a FAILED status on
  // a 200 — so the body is the only place the real reason lives.
  let errorCode = `HTTP_${response.status}`;
  let message = `${response.status} ${response.statusText}`;
  try {
    const body = await response.json();
    if (body?.message) message = body.message;
    if (body?.error_code) errorCode = body.error_code;
  } catch {
    // Non-JSON error body (a proxy, or a static 404) — keep the status line.
  }
  return new MinilakeApiError(response.status, errorCode, message);
}

/** Perform a request and parse the JSON response. */
export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, raw, query, signal, headers = {} } = options;

  const init: RequestInit = { method, signal, headers: { ...headers } };
  if (raw !== undefined) {
    init.body = raw;
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
  }

  const response = await fetch(buildUrl(path, query), init);
  if (!response.ok) throw await toApiError(response);

  if (response.status === 204) return undefined as T;
  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

/** Perform a request and return the raw response (downloads, HEAD probes). */
export async function apiFetchRaw(path: string, options: RequestOptions = {}): Promise<Response> {
  const { method = "GET", body, raw, query, signal, headers = {} } = options;

  const init: RequestInit = { method, signal, headers: { ...headers } };
  if (raw !== undefined) {
    init.body = raw;
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
  }

  const response = await fetch(buildUrl(path, query), init);
  if (!response.ok) throw await toApiError(response);
  return response;
}

/** Human-readable message for any thrown value, for toasts and error panels. */
export function errorMessage(error: unknown): string {
  if (error instanceof MinilakeApiError) return error.message;
  if (error instanceof Error) return error.message;
  return String(error);
}
