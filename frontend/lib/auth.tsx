"use client";

/**
 * Auth context: login (+ MFA/TOTP step), register, logout, session restore.
 * Access token lives in memory; the refresh token restores the session on
 * reload (see lib/token-store.ts for the httpOnly-cookie production TODO).
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
import { clearTokens, getRefreshToken, setAccessToken, setRefreshToken } from "@/lib/token-store";
import type { LoginResponse, UserOut } from "@/lib/types";

export interface AuthContextValue {
  state: AuthState;
  isAdmin: boolean;
  login: (email: string, password: string) => Promise<void>;
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

  // Restore session once on mount: refresh token -> access token -> /me.
  useEffect(() => {
    if (booted.current) return;
    booted.current = true;
    (async () => {
      if (!getRefreshToken()) {
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
    setAccessToken(tokens.access_token);
    setRefreshToken(tokens.refresh_token);
    const user = await fetchMe();
    dispatch({ type: "AUTHENTICATED", user });
  }, []);

  const login = useCallback(
    async (email: string, password: string) => {
      dispatch({ type: "SUBMIT" });
      try {
        const response = await api.post<LoginResponse>(
          "/api/auth/login",
          { email, password },
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
          "/api/auth/login/mfa",
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
    const refreshToken = getRefreshToken();
    if (refreshToken) {
      // Best-effort server-side revocation; local logout happens regardless.
      try {
        await api.post("/api/auth/logout", { refresh_token: refreshToken }, { silent: true });
      } catch {
        /* gateway down: still log out locally */
      }
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
