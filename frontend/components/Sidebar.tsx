"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { useSettings } from "@/lib/settings";
import { Badge } from "@/components/ui";

const NAV_ITEMS: { href: string; label: string }[] = [
  { href: "/dashboard", label: "Overview" },
  { href: "/autonomy", label: "Autonomy" },
  { href: "/strategies", label: "Strategies" },
  { href: "/risk", label: "Risk" },
  { href: "/markets", label: "Markets" },
  { href: "/brokers", label: "Brokers" },
  { href: "/backtests", label: "Backtests" },
  { href: "/executions", label: "Executions" },
  { href: "/alerts", label: "Alerts" },
];

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { state, logout } = useAuth();
  const { accountId, setAccountId, uiMode } = useSettings();

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <span className="brand-dot" aria-hidden="true" />
        TradingPlatform
      </div>

      <div className="sidebar-mode">
        {uiMode === "live" ? (
          <Badge tone="red">REAL · LIVE</Badge>
        ) : (
          <Badge tone="accent">DEMO · PAPER</Badge>
        )}
      </div>

      <nav className="sidebar-nav" aria-label="Main navigation">
        {NAV_ITEMS.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={`nav-link ${pathname?.startsWith(item.href) ? "active" : ""}`}
          >
            {item.label}
          </Link>
        ))}
      </nav>

      <div className="sidebar-footer">
        <label className="label" htmlFor="sidebar-account">
          Account
        </label>
        <input
          id="sidebar-account"
          className="input input-sm"
          key={accountId}
          defaultValue={accountId}
          onBlur={(e) => setAccountId(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") setAccountId((e.target as HTMLInputElement).value);
          }}
        />
        <div className="sidebar-user" title={state.user?.email ?? ""}>
          {state.user?.email ?? ""}
        </div>
        <button
          type="button"
          className="btn btn-block"
          onClick={async () => {
            await logout();
            router.replace("/login");
          }}
        >
          Log out
        </button>
      </div>
    </aside>
  );
}
