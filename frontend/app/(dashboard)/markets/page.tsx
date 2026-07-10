"use client";

/**
 * Markets: the market classes with the global (admin) flag and the per-user
 * toggle. effective = global AND user — a user can never re-enable a market
 * an admin disabled. GET /config/me/markets, PUT /config/me/markets,
 * PATCH /config/markets/{id} (admin).
 */

import { useCallback, useEffect, useState } from "react";
import { useToast } from "@/components/Toast";
import { Badge, EmptyState, ErrorBanner, LoadingSkeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { UserMarketOut } from "@/lib/types";

export default function MarketsPage() {
  const { isAdmin } = useAuth();
  const { push } = useToast();
  const [markets, setMarkets] = useState<UserMarketOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setMarkets(await api.get<UserMarketOut[]>("/config/me/markets", { silent: true }));
      setError(null);
    } catch {
      setError("gateway market configuration is not responding.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const setUserToggle = async (market: UserMarketOut, enabled: boolean) => {
    setBusy(market.market_id);
    try {
      const updated = await api.put<UserMarketOut[]>("/config/me/markets", [
        { market_id: market.market_id, enabled },
      ]);
      setMarkets(updated);
      push(`${market.name}: ${enabled ? "enabled" : "disabled"} for you.`, "success");
    } catch {
      /* toasted */
    } finally {
      setBusy(null);
    }
  };

  const setGlobalToggle = async (market: UserMarketOut, enabled: boolean) => {
    setBusy(market.market_id);
    try {
      await api.patch(`/config/markets/${market.market_id}`, { enabled });
      await load();
      push(`${market.name}: globally ${enabled ? "enabled" : "disabled"}.`, "success");
    } catch {
      /* toasted (403 for non-admin) */
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <div className="page-head">
        <h1>Markets</h1>
        {!isAdmin ? <Badge tone="neutral">global toggles are admin-only</Badge> : null}
      </div>

      {error ? <ErrorBanner message={error} /> : null}

      {loading ? (
        <LoadingSkeleton rows={5} />
      ) : markets.length === 0 ? (
        <EmptyState
          title="No markets configured"
          hint="Markets are seeded by the gateway migration."
        />
      ) : (
        <div className="card table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Market</th>
                <th>Code</th>
                <th>Asset class</th>
                <th>Global (admin)</th>
                <th>My toggle</th>
                <th>Effective</th>
              </tr>
            </thead>
            <tbody>
              {markets.map((m) => (
                <tr key={m.market_id}>
                  <td>{m.name}</td>
                  <td>{m.code}</td>
                  <td>{m.asset_class}</td>
                  <td>
                    <input
                      type="checkbox"
                      className="toggle"
                      aria-label={`Global toggle ${m.name}`}
                      checked={m.market_enabled}
                      disabled={!isAdmin || busy === m.market_id}
                      onChange={(e) => void setGlobalToggle(m, e.target.checked)}
                    />
                  </td>
                  <td>
                    <input
                      type="checkbox"
                      className="toggle"
                      aria-label={`My toggle ${m.name}`}
                      checked={m.user_enabled}
                      disabled={busy === m.market_id}
                      onChange={(e) => void setUserToggle(m, e.target.checked)}
                    />
                  </td>
                  <td>
                    {m.effective_enabled ? (
                      <Badge tone="green">enabled</Badge>
                    ) : (
                      <Badge tone="neutral">disabled</Badge>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
