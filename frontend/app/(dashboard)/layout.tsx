"use client";

import type { ReactNode } from "react";
import { RouteGuard } from "@/components/RouteGuard";
import { Sidebar } from "@/components/Sidebar";

/** Shared sidebar layout + auth guard for every dashboard page. */
export default function DashboardLayout({ children }: { children: ReactNode }) {
  return (
    <RouteGuard>
      <div className="shell">
        <Sidebar />
        <main className="main">{children}</main>
      </div>
    </RouteGuard>
  );
}
