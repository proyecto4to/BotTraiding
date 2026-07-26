/** api client: auth header injection + 401 -> refresh -> retry-once.
 *
 * The refresh token is not in this layer any more — it is an httpOnly cookie
 * the gateway owns. What these tests pin is that the client asks the gateway to
 * refresh (carrying cookies and the CSRF echo) and never handles the token. */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** The gateway's readable CSRF cookie; the httpOnly refresh cookie is by
 *  definition invisible to this code, so there is nothing to fake for it. */
function setCsrfCookie(value: string | null): void {
  if (value === null) {
    document.cookie = "tp_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
  } else {
    document.cookie = `tp_csrf=${value}; path=/`;
  }
}

describe("api client 401-refresh-retry", () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
    setCsrfCookie(null);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    setCsrfCookie(null);
  });

  it("refreshes once on 401 and retries the original request", async () => {
    setCsrfCookie("csrf-1");
    const fetchMock = vi
      .fn()
      // 1. original request with the stale token -> 401
      .mockResolvedValueOnce(jsonResponse(401, { detail: "expired" }))
      // 2. POST /api/session/refresh -> a new access token (refresh stays in the cookie)
      .mockResolvedValueOnce(jsonResponse(200, { access_token: "new-access" }))
      // 3. retried original request -> data
      .mockResolvedValueOnce(jsonResponse(200, { account_id: "default", equity: 1000 }));
    vi.stubGlobal("fetch", fetchMock);

    const { api } = await import("@/lib/api");
    const tokens = await import("@/lib/token-store");
    tokens.setAccessToken("stale-access");

    const data = await api.get<{ account_id: string }>("/api/portfolio/default");

    expect(data.account_id).toBe("default");
    expect(fetchMock).toHaveBeenCalledTimes(3);

    // The refresh went to the gateway session endpoint...
    const refreshUrl = String(fetchMock.mock.calls[1][0]);
    expect(refreshUrl).toContain("/api/session/refresh");
    const refreshInit = fetchMock.mock.calls[1][1]!;
    // ...carried the cookie and the CSRF echo...
    expect(refreshInit.credentials).toBe("include");
    expect((refreshInit.headers as Record<string, string>)["X-CSRF-Token"]).toBe("csrf-1");
    // ...and sent no refresh token of its own.
    expect(refreshInit.body).toBeUndefined();

    // The retry carried the NEW access token.
    const retryHeaders = fetchMock.mock.calls[2][1]!.headers as Record<string, string>;
    expect(retryHeaders["Authorization"]).toBe("Bearer new-access");

    expect(tokens.getAccessToken()).toBe("new-access");
  });

  it("clears the access token and notifies listeners when the refresh fails", async () => {
    setCsrfCookie("csrf-1");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(401, { detail: "expired" }))
      .mockResolvedValueOnce(jsonResponse(401, { detail: "session expired" }));
    vi.stubGlobal("fetch", fetchMock);

    const { api, onAuthFailure, ApiError } = await import("@/lib/api");
    const tokens = await import("@/lib/token-store");
    tokens.setAccessToken("stale-access");

    const authFailed = vi.fn();
    onAuthFailure(authFailed);

    await expect(
      api.get("/api/portfolio/default", { silent: true }),
    ).rejects.toBeInstanceOf(ApiError);

    expect(fetchMock).toHaveBeenCalledTimes(2); // no retry without a new token
    expect(authFailed).toHaveBeenCalledTimes(1);
    expect(tokens.getAccessToken()).toBeNull();
  });

  it("does not try to refresh on auth endpoints (401 = bad credentials)", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(401, { detail: "Invalid credentials" }));
    vi.stubGlobal("fetch", fetchMock);

    const { api, ApiError } = await import("@/lib/api");
    await expect(
      api.post("/api/auth/login", { email: "a@b.c", password: "x" }, { silent: true }),
    ).rejects.toBeInstanceOf(ApiError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("does not try to refresh a failed login on the session endpoint", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(401, { detail: "Invalid credentials" }));
    vi.stubGlobal("fetch", fetchMock);

    const { api, ApiError } = await import("@/lib/api");
    await expect(
      api.post("/api/session/login", { username: "u", password: "x" }, { silent: true }),
    ).rejects.toBeInstanceOf(ApiError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("sends the CSRF echo on session calls", async () => {
    setCsrfCookie("csrf-42");
    // 204 carries no body, so it cannot go through jsonResponse.
    const fetchMock = vi.fn().mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    const { api } = await import("@/lib/api");
    await api.post("/api/session/logout", undefined, { silent: true });

    const headers = fetchMock.mock.calls[0][1]!.headers as Record<string, string>;
    expect(headers["X-CSRF-Token"]).toBe("csrf-42");
    expect(fetchMock.mock.calls[0][1]!.credentials).toBe("include");
  });
});
