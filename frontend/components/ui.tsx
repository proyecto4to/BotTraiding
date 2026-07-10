"use client";

/** Small shared display primitives: badges, banners, empty/loading states. */

import type { ReactNode } from "react";

export function Badge({
  tone = "neutral",
  children,
}: {
  tone?: "neutral" | "green" | "red" | "amber" | "accent";
  children: ReactNode;
}) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

export function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="banner banner-error" role="alert">
      <strong>Backend unavailable.</strong> {message}
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="empty">
      <p className="empty-title">{title}</p>
      {hint ? <p className="empty-hint">{hint}</p> : null}
    </div>
  );
}

export function LoadingSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton" />
      ))}
    </div>
  );
}

export function StatCard({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "pos" | "neg" | "";
}) {
  return (
    <div className="card stat-card">
      <div className="stat-label">{label}</div>
      <div className={`stat-value ${tone ?? ""}`}>{value}</div>
      {sub ? <div className="stat-sub">{sub}</div> : null}
    </div>
  );
}

export function SectionTitle({ children }: { children: ReactNode }) {
  return <h2 className="section-title">{children}</h2>;
}

export function circuitBreakerTone(state: string): "green" | "amber" | "red" {
  const normalized = state.toUpperCase();
  if (normalized === "NORMAL") return "green";
  if (normalized.includes("HALT") || normalized.includes("OPEN")) return "red";
  return "amber";
}
