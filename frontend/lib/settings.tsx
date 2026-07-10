"use client";

/**
 * App-level display settings: selected account id and the Demo/Real (paper/
 * live) UI mode indicator. This is presentation state only — the execution
 * mode actually applied to an order is enforced server-side by the
 * execution-engine (admin-gated override), never by the frontend.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

export type UiExecutionMode = "paper" | "live";

interface SettingsContextValue {
  accountId: string;
  setAccountId: (id: string) => void;
  uiMode: UiExecutionMode;
  setUiMode: (mode: UiExecutionMode) => void;
}

const ACCOUNT_KEY = "tp.account_id";
const MODE_KEY = "tp.ui_mode";

const SettingsContext = createContext<SettingsContextValue | null>(null);

function readStored(key: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  try {
    return window.localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [accountId, setAccountIdState] = useState("default");
  const [uiMode, setUiModeState] = useState<UiExecutionMode>("paper");

  useEffect(() => {
    setAccountIdState(readStored(ACCOUNT_KEY, "default"));
    const mode = readStored(MODE_KEY, "paper");
    setUiModeState(mode === "live" ? "live" : "paper");
  }, []);

  const setAccountId = useCallback((id: string) => {
    const value = id.trim() || "default";
    setAccountIdState(value);
    try {
      window.localStorage.setItem(ACCOUNT_KEY, value);
    } catch {
      /* ignore */
    }
  }, []);

  const setUiMode = useCallback((mode: UiExecutionMode) => {
    setUiModeState(mode);
    try {
      window.localStorage.setItem(MODE_KEY, mode);
    } catch {
      /* ignore */
    }
  }, []);

  return (
    <SettingsContext.Provider value={{ accountId, setAccountId, uiMode, setUiMode }}>
      {children}
    </SettingsContext.Provider>
  );
}

export function useSettings(): SettingsContextValue {
  const ctx = useContext(SettingsContext);
  if (!ctx) throw new Error("useSettings must be used inside <SettingsProvider>");
  return ctx;
}
