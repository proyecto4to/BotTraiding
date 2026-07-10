"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/lib/auth";
import { LoadingSkeleton } from "@/components/ui";

/** Root: route to the dashboard when authenticated, /login otherwise. */
export default function Home() {
  const { state } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (state.status === "authenticated") router.replace("/dashboard");
    else if (state.status === "anonymous" || state.status === "mfa_required") {
      router.replace("/login");
    }
  }, [state.status, router]);

  return (
    <div className="guard-loading">
      <LoadingSkeleton rows={3} />
    </div>
  );
}
