/** api client: auth header injection + 401 -> refresh -> retry-once. */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("api client 401-refresh-retry", () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("refreshes once on 401 and retries the original request", async () => {
    const fetchMock = vi
      .fn()
      // 1. original request with the stale token -> 401
      .mockResolvedValueOnce(jsonResponse(401, { detail: "expired" }))
      // 2. POST /api/auth/refresh -> new pair
      .mockResolvedValueOnce(
        jsonResponse(200, { access_token: "new-access", refresh_token: "new-refresh" }),
      )
      // 3. retried original request -> data
      .mockResolvedValueOnce(jsonResponse(200, { account_id: "default", equity: 1000 }));
    vi.stubGlobal("fetch", fetchMock);

    const { api } = await import("@/lib/api");
    const tokens = await import("@/lib/token-store");
    tokens.setAccessToken("stale-access");
    tokens.setRefreshToken("old-refresh");

    const data = await api.get<{ account_id: string }>("/api/portfolio/default");

    expect(data.account_id).toBe("default");
    expect(fetchMock).toHaveBeenCalledTimes(3);

    // Refresh call went to the auth endpoint with the stored refresh token.
    const refreshUrl = String(fetchMock.mock.calls[1][0]);
    expect(refreshUrl).toContain("/api/auth/refresh");
    expect(JSON.parse(fetchMock.mock.calls[1][1]!.body as string)).toEqual({
      refresh_token: "old-refresh",
    });

    // The retry carried the NEW access token.
    const retryHeaders = fetchMock.mock.calls[2][1]!.headers as Record<string, string>;
    expect(retryHeaders["Authorization"]).toBe("Bearer new-access");

    // New pair persisted.
    expect(tokens.getAccessToken()).toBe("new-access");
    expect(tokens.getRefreshToken()).toBe("new-refresh");
  });

  it("clears tokens and notifies listeners when the refresh fails", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(401, { detail: "expired" }))
      .mockResolvedValueOnce(jsonResponse(401, { detail: "refresh revoked" }));
    vi.stubGlobal("fetch", fetchMock);

    const { api, onAuthFailure, ApiError } = await import("@/lib/api");
    const tokens = await import("@/lib/token-store");
    tokens.setAccessToken("stale-access");
    tokens.setRefreshToken("revoked-refresh");

    const authFailed = vi.fn();
    onAuthFailure(authFailed);

    await expect(
      api.get("/api/portfolio/default", { silent: true }),
    ).rejects.toBeInstanceOf(ApiError);

    expect(fetchMock).toHaveBeenCalledTimes(2); // no retry without a new token
    expect(authFailed).toHaveBeenCalledTimes(1);
    expect(tokens.getAccessToken()).toBeNull();
    expect(tokens.getRefreshToken()).toBeNull();
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
});
