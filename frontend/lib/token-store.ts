/**
 * Token storage.
 *
 * - Access token: memory only (module scope) — never persisted, gone on reload.
 * - Refresh token: NOT HERE. It lives in an httpOnly cookie set by the gateway
 *   (`/api/session/*`, see services/gateway/app/session.py) that JavaScript
 *   cannot read. It used to sit in localStorage, which meant any XSS on the
 *   dashboard could lift it and keep minting access tokens long after the page
 *   was closed. A session now survives a reload because the browser replays
 *   that cookie to POST /api/session/refresh, not because we stored anything.
 * - CSRF token: a readable cookie the client echoes back in `X-CSRF-Token` on
 *   session calls. Not a credential — it only has to be unguessable from
 *   another origin, which the same-origin policy already guarantees.
 */

const CSRF_COOKIE = "tp_csrf";

let accessToken: string | null = null;

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

/** Value of the CSRF cookie, or null when there is no session. */
export function getCsrfToken(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(
    new RegExp(`(?:^|;\\s*)${CSRF_COOKIE}=([^;]*)`),
  );
  return match ? decodeURIComponent(match[1]) : null;
}

/** Headers for a session call: the CSRF echo, when we have one. */
export function csrfHeaders(): Record<string, string> {
  const token = getCsrfToken();
  return token ? { "X-CSRF-Token": token } : {};
}

/**
 * Forget the in-memory access token. The refresh cookie is the gateway's to
 * clear (POST /api/session/logout) — the browser cannot delete an httpOnly
 * cookie itself, which is exactly the point.
 */
export function clearTokens(): void {
  setAccessToken(null);
}
