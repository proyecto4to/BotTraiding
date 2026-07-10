"use client";

import type { ReactNode } from "react";
import { ToastProvider } from "@/components/Toast";
import { AuthProvider } from "@/lib/auth";
import { SettingsProvider } from "@/lib/settings";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <ToastProvider>
      <SettingsProvider>
        <AuthProvider>{children}</AuthProvider>
      </SettingsProvider>
    </ToastProvider>
  );
}
