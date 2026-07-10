import { describe, expect, it } from "vitest";
import { authReducer, initialAuthState, isAdmin } from "@/lib/auth-reducer";
import type { UserOut } from "@/lib/types";

const user: UserOut = {
  id: "u1",
  email: "trader@example.com",
  is_active: true,
  mfa_enabled: true,
  roles: ["trader"],
};

describe("authReducer", () => {
  it("starts booting and settles to anonymous", () => {
    expect(initialAuthState.status).toBe("booting");
    const next = authReducer(initialAuthState, { type: "BOOT_DONE_ANONYMOUS" });
    expect(next.status).toBe("anonymous");
    expect(next.user).toBeNull();
  });

  it("moves to mfa_required with the pending token when MFA is enabled", () => {
    let state = authReducer(initialAuthState, { type: "BOOT_DONE_ANONYMOUS" });
    state = authReducer(state, { type: "SUBMIT" });
    expect(state.status).toBe("submitting");
    state = authReducer(state, { type: "MFA_REQUIRED", mfaPendingToken: "pending-123" });
    expect(state.status).toBe("mfa_required");
    expect(state.mfaPendingToken).toBe("pending-123");
  });

  it("authenticates and clears the pending token", () => {
    let state = authReducer(initialAuthState, {
      type: "MFA_REQUIRED",
      mfaPendingToken: "pending-123",
    });
    state = authReducer(state, { type: "AUTHENTICATED", user });
    expect(state.status).toBe("authenticated");
    expect(state.user?.email).toBe("trader@example.com");
    expect(state.mfaPendingToken).toBeNull();
    expect(state.error).toBeNull();
  });

  it("keeps the user on the MFA step after a bad TOTP code", () => {
    let state = authReducer(initialAuthState, {
      type: "MFA_REQUIRED",
      mfaPendingToken: "pending-123",
    });
    state = authReducer(state, { type: "SUBMIT" });
    state = authReducer(state, { type: "AUTH_ERROR", message: "Invalid MFA code" });
    expect(state.status).toBe("mfa_required");
    expect(state.mfaPendingToken).toBe("pending-123");
    expect(state.error).toBe("Invalid MFA code");
  });

  it("returns to anonymous after a bad password", () => {
    let state = authReducer(initialAuthState, { type: "BOOT_DONE_ANONYMOUS" });
    state = authReducer(state, { type: "SUBMIT" });
    state = authReducer(state, { type: "AUTH_ERROR", message: "Invalid credentials" });
    expect(state.status).toBe("anonymous");
    expect(state.error).toBe("Invalid credentials");
  });

  it("logout resets everything", () => {
    let state = authReducer(initialAuthState, { type: "AUTHENTICATED", user });
    state = authReducer(state, { type: "LOGGED_OUT" });
    expect(state.status).toBe("anonymous");
    expect(state.user).toBeNull();
  });

  it("isAdmin checks the admin role", () => {
    expect(isAdmin(user)).toBe(false);
    expect(isAdmin({ ...user, roles: ["admin", "trader"] })).toBe(true);
    expect(isAdmin(null)).toBe(false);
  });
});
