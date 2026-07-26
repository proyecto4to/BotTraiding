"use client";

/**
 * Auth context: login (+ MFA/TOTP step), register, logout, session restore.
 *
 * The access token lives in memory only. The refresh token is never handled
 * here at all: the gateway keeps it in an httpOnly cookie (/api/session/*), so
 * restoring a session is just asking the gateway to refresh and letting the
 * browser replay a cookie this code cannot read.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useReducer,
  useRef,
  type ReactNode,
} from "react";
import { api, ApiError, onAuthFailure, refreshAccessToken } from "@/lib/api";
import {
  authReducer,
  initialAuthState,
  isAdmin,
  type AuthState,
} from "@/lib/auth-reducer";
import { clearTokens, getCsrfToken, setAccessToken } from "@/lib/token-store";
import type { LoginResponse, UserOut } from "@/lib/types";

export interface AuthContextValue {
  state: AuthState;
  isAdmin: boolean;
  login: (identifier: string, password: string) => Promise<void>;
  submitMfa: (code: string) => Promise<void>;
  cancelMfa: () => void;
  register: (email: string, password: string) => Promise<UserOut>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

async function fetchMe(): Promise<UserOut> {
  return api.get<UserOut>("/api/auth/me", { silent: true });
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(authReducer, initialAuthState);
  const booted = useRef(false);

  // Restore session once on mount: refresh cookie -> access token -> /me.
  useEffect(() => {
    if (booted.current) return;
    booted.current = true;
    (async () => {
      // The refresh cookie is httpOnly and unreadable, so the CSRF cookie is
      // the only visible sign a session might exist. Skipping the round-trip
      // without it just avoids a guaranteed 401 on every anonymous page load.
      if (!getCsrfToken()) {
        dispatch({ type: "BOOT_DONE_ANONYMOUS" });
        return;
      }
      const refreshed = await refreshAccessToken();
      if (!refreshed) {
        clearTokens();
        dispatch({ type: "BOOT_DONE_ANONYMOUS" });
        return;
      }
      try {
        const user = await fetchMe();
        dispatch({ type: "AUTHENTICATED", user });
      } catch {
        clearTokens();
        dispatch({ type: "BOOT_DONE_ANONYMOUS" });
      }
    })();
  }, []);

  // Refresh failed mid-session (revoked/expired) -> back to login.
  useEffect(
    () =>
      onAuthFailure(() => {
        dispatch({ type: "LOGGED_OUT" });
      }),
    [],
  );

  const applyTokenPair = useCallback(async (tokens: LoginResponse) => {
    // Only the access token comes back in the body; the refresh token went
    // straight into the gateway's httpOnly cookie and never touches this code.
    setAccessToken(tokens.access_token);
    const user = await fetchMe();
    dispatch({ type: "AUTHENTICATED", user });
  }, []);

  const login = useCallback(
    async (identifier: string, password: string) => {
      dispatch({ type: "SUBMIT" });
      // The single operator logs in with a username; regular accounts use an
      // email. An "@" disambiguates which field the backend should match.
      const credentials = identifier.includes("@")
        ? { email: identifier, password }
        : { username: identifier, password };
      try {
        const response = await api.post<LoginResponse>(
          "/api/session/login",
          credentials,
          { silent: true },
        );
        if (response.mfa_required && response.mfa_pending_token) {
          dispatch({ type: "MFA_REQUIRED", mfaPendingToken: response.mfa_pending_token });
          return;
        }
        await applyTokenPair(response);
      } catch (err) {
        dispatch({ type: "AUTH_ERROR", message: messageOf(err, "Login failed") });
      }
    },
    [applyTokenPair],
  );

  const submitMfa = useCallback(
    async (code: string) => {
      const pending = state.mfaPendingToken;
      if (!pending) return;
      dispatch({ type: "SUBMIT" });
      try {
        const response = await api.post<LoginResponse>(
          "/api/session/login/mfa",
          { mfa_pending_token: pending, code },
          { silent: true },
        );
        await applyTokenPair(response);
      } catch (err) {
        dispatch({ type: "AUTH_ERROR", message: messageOf(err, "Invalid MFA code") });
      }
    },
    [applyTokenPair, state.mfaPendingToken],
  );

  const cancelMfa = useCallback(() => dispatch({ type: "MFA_CANCELLED" }), []);

  const register = useCallback(async (email: string, password: string) => {
    return api.post<UserOut>("/api/auth/register", { email, password }, { silent: true });
  }, []);

  const logout = useCallback(async () => {
    // The gateway revokes the refresh token upstream and clears the cookie —
    // this code cannot delete an httpOnly cookie, which is the whole point.
    try {
      await api.post("/api/session/logout", undefined, { silent: true });
    } catch {
      /* gateway down: still drop the in-memory token and log out locally */
    }
    clearTokens();
    dispatch({ type: "LOGGED_OUT" });
  }, []);

  const value: AuthContextValue = {
    state,
    isAdmin: isAdmin(state.user),
    login,
    submitMfa,
    cancelMfa,
    register,
    logout,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

function messageOf(err: unknown, fallback: string): string {
  if (err instanceof ApiError && err.status === 0) return "Gateway unreachable";
  if (err instanceof Error && err.message) return err.message;
  return fallback;
}
