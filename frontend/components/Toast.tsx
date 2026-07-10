"use client";

/** Minimal toast stack. The api client reports errors here via
 * setErrorReporter; pages can push success toasts through useToast(). */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { setErrorReporter } from "@/lib/api";

export type ToastKind = "error" | "success" | "info";

interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
}

interface ToastContextValue {
  push: (message: string, kind?: ToastKind) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);

  const push = useCallback((message: string, kind: ToastKind = "info") => {
    const id = nextId.current++;
    setToasts((current) => [...current.slice(-4), { id, kind, message }]);
    setTimeout(() => {
      setToasts((current) => current.filter((t) => t.id !== id));
    }, 5000);
  }, []);

  useEffect(() => {
    setErrorReporter((message) => push(message, "error"));
    return () => setErrorReporter(null);
  }, [push]);

  return (
    <ToastContext.Provider value={{ push }}>
      {children}
      <div className="toast-stack" role="status" aria-live="polite">
        {toasts.map((toast) => (
          <div key={toast.id} className={`toast toast-${toast.kind}`}>
            {toast.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return ctx;
}
