/**
 * Typed gateway client. ALL backend traffic goes through the gateway
 * (docs/ARCHITECTURE.md: clients never call an internal service directly).
 *
 * - Injects Authorization: Bearer <access token> on every call.
 * - On 401: refreshes once via POST /api/auth/refresh (single-flight) and
 *   retries the original request exactly once.
 * - On refresh failure: clears tokens and notifies subscribers (the
 *   AuthProvider logs the user out).
 * - Errors are reported to an injectable reporter (the ToastProvider) unless
 *   the call opts out with { silent: true } — pages that expect a backend to
 *   be down use silent + their own banner/empty state.
 */

import {
  clearTokens,
  csrfHeaders,
  getAccessToken,
  setAccessToken,
} from "@/lib/token-store";
import type { LoginResponse } from "@/lib/types";

export const GATEWAY_URL =
  process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : `Request failed (${status})`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export interface RequestOptions {
  /** Do not report this error to the global toast reporter. */
  silent?: boolean;
  /** Extra query params appended to the URL (null/undefined skipped). */
  query?: Record<string, string | number | boolean | null | undefined>;
  signal?: AbortSignal;
}

type ErrorReporter = (message: string) => void;
type AuthFailureListener = () => void;

let errorReporter: ErrorReporter | null = null;
const authFailureListeners = new Set<AuthFailureListener>();

export function setErrorReporter(reporter: ErrorReporter | null): void {
  errorReporter = reporter;
}

export function onAuthFailure(listener: AuthFailureListener): () => void {
  authFailureListeners.add(listener);
  return () => authFailureListeners.delete(listener);
}

function notifyAuthFailure(): void {
  authFailureListeners.forEach((listener) => listener());
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = new URL(path, GATEWAY_URL);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== null && value !== undefined && value !== "") {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return url.toString();
}

async function parseBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function detailOf(body: unknown): unknown {
  if (body && typeof body === "object" && "detail" in body) {
    return (body as { detail: unknown }).detail;
  }
  return body;
}

// Single-flight refresh: concurrent 401s share one refresh round-trip.
let refreshInFlight: Promise<boolean> | null = null;

async function doRefresh(): Promise<boolean> {
  // No token to send: the gateway reads the httpOnly refresh cookie the browser
  // attaches to /api/session/*. `credentials: "include"` is what makes it do so
  // cross-origin (dashboard :3000 -> gateway :8000).
  try {
    const response = await fetch(buildUrl("/api/session/refresh"), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", ...csrfHeaders() },
    });
    if (!response.ok) return false;
    const body = (await parseBody(response)) as LoginResponse | null;
    if (!body?.access_token) return false;
    setAccessToken(body.access_token);
    return true;
  } catch {
    return false;
  }
}

export async function refreshAccessToken(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = doRefresh().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

async function rawFetch(
  method: string,
  path: string,
  body: unknown,
  options: RequestOptions,
): Promise<Response> {
  const headers: Record<string, string> = {};
  const token = getAccessToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  // Session calls carry the CSRF echo; the gateway rejects them without it.
  if (path.startsWith("/api/session/")) Object.assign(headers, csrfHeaders());
  return fetch(buildUrl(path, options.query), {
    method,
    headers,
    // Needed so the browser stores the Set-Cookie from /api/session/login and
    // replays it on refresh/logout. Harmless elsewhere: the refresh cookie is
    // Path-scoped to /api/session, so ordinary /api/* calls never carry it.
    credentials: "include",
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: options.signal,
  });
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  options: RequestOptions = {},
): Promise<T> {
  let response: Response;
  try {
    response = await rawFetch(method, path, body, options);
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    const apiError = new ApiError(0, "Gateway unreachable");
    if (!options.silent) errorReporter?.(apiError.message);
    throw apiError;
  }

  // 401 → refresh once → retry once. Auth/session endpoints are exempt (a 401
  // there means bad credentials or a dead session, not an expired access token).
  if (
    response.status === 401 &&
    !path.startsWith("/api/auth/") &&
    !path.startsWith("/api/session/")
  ) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      response = await rawFetch(method, path, body, options);
    } else {
      clearTokens();
      notifyAuthFailure();
    }
  }

  const parsed = await parseBody(response);
  if (!response.ok) {
    const detail = detailOf(parsed);
    const apiError = new ApiError(
      response.status,
      typeof detail === "string" ? detail : JSON.stringify(detail ?? ""),
    );
    if (!options.silent) errorReporter?.(apiError.message);
    throw apiError;
  }
  return parsed as T;
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) =>
    request<T>("GET", path, undefined, options),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>("POST", path, body, options),
  put: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>("PUT", path, body, options),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>("PATCH", path, body, options),
  delete: <T>(path: string, options?: RequestOptions) =>
    request<T>("DELETE", path, undefined, options),
};
