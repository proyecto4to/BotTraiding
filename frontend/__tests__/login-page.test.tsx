/** Login page render with mocked fetch: credentials -> MFA-pending -> TOTP step. */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/login",
}));

import LoginPage from "@/app/login/page";
import { Providers } from "@/app/providers";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("LoginPage", () => {
  beforeEach(() => {
    window.localStorage.clear();
    replace.mockClear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the credentials form and switches to the TOTP step on mfa_required", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/session/login")) {
        return Promise.resolve(
          // No refresh_token in the body: the gateway keeps it in an httpOnly
          // cookie, and an MFA challenge has no tokens yet anyway.
          jsonResponse(200, {
            access_token: null,
            token_type: "bearer",
            mfa_required: true,
            mfa_pending_token: "pending-token-xyz",
          }),
        );
      }
      return Promise.resolve(jsonResponse(404, { detail: "not found" }));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <Providers>
        <LoginPage />
      </Providers>,
    );

    // Credentials step renders.
    const email = await screen.findByLabelText(/email/i);
    const password = screen.getByLabelText(/password/i);
    expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument();

    fireEvent.change(email, { target: { value: "trader@example.com" } });
    fireEvent.change(password, { target: { value: "hunter2hunter2" } });
    fireEvent.submit(screen.getByRole("form", { name: /login form/i }));

    // MFA step appears with the TOTP input.
    await waitFor(() => {
      expect(screen.getByLabelText(/totp code/i)).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: /verify code/i })).toBeInTheDocument();

    // The login POST went through the gateway's session route (BFF).
    const loginCall = fetchMock.mock.calls.find((call) =>
      String(call[0]).includes("/api/session/login"),
    );
    expect(loginCall).toBeDefined();
    expect(JSON.parse((loginCall![1] as RequestInit).body as string)).toEqual({
      email: "trader@example.com",
      password: "hunter2hunter2",
    });
  });

  it("shows an error banner on invalid credentials", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(401, { detail: "Invalid credentials" }));
    vi.stubGlobal("fetch", fetchMock);

    render(
      <Providers>
        <LoginPage />
      </Providers>,
    );

    fireEvent.change(await screen.findByLabelText(/email/i), {
      target: { value: "trader@example.com" },
    });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "wrongpass" } });
    fireEvent.submit(screen.getByRole("form", { name: /login form/i }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/invalid credentials/i);
    });
  });
});
