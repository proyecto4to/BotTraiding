"use client";

/** Redirects unauthenticated visitors to /login. Wraps every dashboard page
 * via the (dashboard) route-group layout. */

import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { useAuth } from "@/lib/auth";
import { LoadingSkeleton } from "@/components/ui";

export function RouteGuard({ children }: { children: ReactNode }) {
  const { state } = useAuth();
  const router = useRouter();

  const blocked = state.status !== "authenticated";

  useEffect(() => {
    if (state.status === "anonymous" || state.status === "mfa_required") {
      router.replace("/login");
    }
  }, [state.status, router]);

  if (blocked) {
    return (
      <div className="guard-loading">
        <LoadingSkeleton rows={4} />
      </div>
    );
  }
  return <>{children}</>;
}
