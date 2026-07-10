"use client";

/** Strategy list: category/market/timeframe filters + enable/disable toggle.
 * GET /api/strategies, PATCH /api/strategies/{key}. */

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useToast } from "@/components/Toast";
import { Badge, EmptyState, ErrorBanner, LoadingSkeleton } from "@/components/ui";
import { api } from "@/lib/api";
import type { StrategySummary } from "@/lib/types";

export default function StrategiesPage() {
  const { push } = useToast();
  const [strategies, setStrategies] = useState<StrategySummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [category, setCategory] = useState("");
  const [market, setMarket] = useState("");
  const [timeframe, setTimeframe] = useState("");
  const [toggling, setToggling] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const list = await api.get<StrategySummary[]>("/api/strategies", {
        silent: true,
        query: { category, market, timeframe },
      });
      setStrategies(list);
      setError(null);
    } catch {
      setError("strategy-engine is not responding.");
    } finally {
      setLoading(false);
    }
  }, [category, market, timeframe]);

  useEffect(() => {
    void load();
  }, [load]);

  // Filter options derived from data (kept when filters shrink the list).
  const [allOptions, setAllOptions] = useState<{
    categories: string[];
    markets: string[];
    timeframes: string[];
  }>({ categories: [], markets: [], timeframes: [] });

  useEffect(() => {
    setAllOptions((prev) => ({
      categories: mergeSorted(prev.categories, strategies.map((s) => s.category)),
      markets: mergeSorted(prev.markets, strategies.flatMap((s) => s.markets)),
      timeframes: mergeSorted(prev.timeframes, strategies.flatMap((s) => s.timeframes)),
    }));
  }, [strategies]);

  const rows = useMemo(() => strategies, [strategies]);

  const toggle = async (strategy: StrategySummary) => {
    setToggling(strategy.key);
    try {
      const updated = await api.patch<StrategySummary>(`/api/strategies/${strategy.key}`, {
        enabled: !strategy.enabled,
      });
      setStrategies((current) =>
        current.map((s) => (s.key === updated.key ? { ...s, enabled: updated.enabled } : s)),
      );
      push(`${updated.name} ${updated.enabled ? "enabled" : "disabled"}.`, "success");
    } catch {
      /* toast already shown by the api client */
    } finally {
      setToggling(null);
    }
  };

  return (
    <>
      <div className="page-head">
        <h1>Strategies</h1>
      </div>

      <div className="filters-row">
        <div className="form-row">
          <label className="label" htmlFor="f-category">
            Category
          </label>
          <select
            id="f-category"
            className="input"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          >
            <option value="">All</option>
            {allOptions.categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>
        <div className="form-row">
          <label className="label" htmlFor="f-market">
            Market
          </label>
          <select
            id="f-market"
            className="input"
            value={market}
            onChange={(e) => setMarket(e.target.value)}
          >
            <option value="">All</option>
            {allOptions.markets.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </div>
        <div className="form-row">
          <label className="label" htmlFor="f-timeframe">
            Timeframe
          </label>
          <select
            id="f-timeframe"
            className="input"
            value={timeframe}
            onChange={(e) => setTimeframe(e.target.value)}
          >
            <option value="">All</option>
            {allOptions.timeframes.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error ? <ErrorBanner message={error} /> : null}

      {loading ? (
        <LoadingSkeleton rows={5} />
      ) : rows.length === 0 ? (
        <EmptyState
          title="No strategies found"
          hint={error ? "The strategy-engine may still be starting." : "Try clearing the filters."}
        />
      ) : (
        <div className="card table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Strategy</th>
                <th>Category</th>
                <th>Markets</th>
                <th>Timeframes</th>
                <th>Status</th>
                <th>Enabled</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.key}>
                  <td>
                    <Link href={`/strategies/${encodeURIComponent(s.key)}`}>{s.name}</Link>
                    <div className="muted" style={{ fontSize: "0.72rem" }}>
                      {s.key} · v{s.version}
                    </div>
                  </td>
                  <td>{s.category}</td>
                  <td>{s.markets.join(", ")}</td>
                  <td>{s.timeframes.join(", ")}</td>
                  <td>
                    {s.enabled ? <Badge tone="green">active</Badge> : <Badge tone="neutral">off</Badge>}
                  </td>
                  <td>
                    <input
                      type="checkbox"
                      className="toggle"
                      aria-label={`Toggle ${s.name}`}
                      checked={s.enabled}
                      disabled={toggling === s.key}
                      onChange={() => void toggle(s)}
                    />
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

function mergeSorted(previous: string[], next: string[]): string[] {
  return Array.from(new Set([...previous, ...next])).sort();
}
