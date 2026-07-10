/**
 * Token storage.
 *
 * - Access token: memory only (module scope) — never persisted, gone on reload.
 * - Refresh token: localStorage so a page reload can restore the session via
 *   POST /api/auth/refresh.
 *
 * PRODUCTION TODO: move the refresh token into an httpOnly, Secure, SameSite
 * cookie set by the gateway (BFF pattern) so it is unreadable from JS and
 * immune to XSS exfiltration. localStorage is a deliberate Fase 13 shortcut,
 * acceptable only for local/dev environments.
 */

const REFRESH_KEY = "tp.refresh_token";

let accessToken: string | null = null;

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(REFRESH_KEY);
  } catch {
    return null;
  }
}

export function setRefreshToken(token: string | null): void {
  if (typeof window === "undefined") return;
  try {
    if (token === null) window.localStorage.removeItem(REFRESH_KEY);
    else window.localStorage.setItem(REFRESH_KEY, token);
  } catch {
    // storage unavailable (private mode etc.) — session lives in memory only
  }
}

export function clearTokens(): void {
  setAccessToken(null);
  setRefreshToken(null);
}
