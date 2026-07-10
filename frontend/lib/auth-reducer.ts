/** Pure auth state machine — kept free of React/fetch so it is unit-testable. */

import type { UserOut } from "@/lib/types";

export type AuthStatus =
  | "booting" // restoring session from refresh token
  | "anonymous"
  | "submitting" // credentials or TOTP in flight
  | "mfa_required"
  | "authenticated";

export interface AuthState {
  status: AuthStatus;
  user: UserOut | null;
  mfaPendingToken: string | null;
  error: string | null;
}

export type AuthAction =
  | { type: "BOOT_DONE_ANONYMOUS" }
  | { type: "SUBMIT" }
  | { type: "MFA_REQUIRED"; mfaPendingToken: string }
  | { type: "AUTHENTICATED"; user: UserOut }
  | { type: "AUTH_ERROR"; message: string }
  | { type: "MFA_CANCELLED" }
  | { type: "LOGGED_OUT" };

export const initialAuthState: AuthState = {
  status: "booting",
  user: null,
  mfaPendingToken: null,
  error: null,
};

export function authReducer(state: AuthState, action: AuthAction): AuthState {
  switch (action.type) {
    case "BOOT_DONE_ANONYMOUS":
      return { ...initialAuthState, status: "anonymous" };
    case "SUBMIT":
      return { ...state, status: "submitting", error: null };
    case "MFA_REQUIRED":
      return {
        status: "mfa_required",
        user: null,
        mfaPendingToken: action.mfaPendingToken,
        error: null,
      };
    case "AUTHENTICATED":
      return {
        status: "authenticated",
        user: action.user,
        mfaPendingToken: null,
        error: null,
      };
    case "AUTH_ERROR":
      return {
        ...state,
        // A failed TOTP keeps the user on the MFA step (pending token is
        // still valid); a failed password submit returns to anonymous.
        status: state.mfaPendingToken ? "mfa_required" : "anonymous",
        error: action.message,
      };
    case "MFA_CANCELLED":
      return { ...initialAuthState, status: "anonymous" };
    case "LOGGED_OUT":
      return { ...initialAuthState, status: "anonymous" };
    default:
      return state;
  }
}

export function isAdmin(user: UserOut | null): boolean {
  return user?.roles.includes("admin") ?? false;
}
