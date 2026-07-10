"use client";

/**
 * Backtests: run form (strategy, symbol, timeframe, dates, frictions) and a
 * results view with the standard metric cards + equity-curve chart.
 * POST /api/backtests/run — the backtester REST layer is still being built,
 * so the page degrades to an explanatory banner when it is not there yet.
 * Metric keys follow services/backtester/app/metrics.py summarize().
 */

import { useEffect, useState, type FormEvent } from "react";
import { EquityCurveChart, type EquitySample } from "@/components/charts/EquityCurveChart";
import { EmptyState, ErrorBanner, SectionTitle, StatCard } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { fmtDateTime, fmtNum, fmtPct } from "@/lib/format";
import type { BacktestResult, StrategySummary } from "@/lib/types";

const METRIC_CARDS: { key: string; label: string; kind: "num" | "pct" }[] = [
  { key: "sharpe", label: "Sharpe", kind: "num" },
  { key: "sortino", label: "Sortino", kind: "num" },
  { key: "calmar", label: "Calmar", kind: "num" },
  { key: "profit_factor", label: "Profit factor", kind: "num" },
  { key: "cagr", label: "CAGR", kind: "pct" },
  { key: "max_drawdown", label: "Max drawdown", kind: "pct" },
  { key: "expectancy", label: "Expectancy", kind: "num" },
  { key: "win_rate", label: "Win rate", kind: "pct" },
];

export default function BacktestsPage() {
  const [strategies, setStrategies] = useState<StrategySummary[]>([]);
  const [form, setForm] = useState({
    strategy_key: "",
    symbol: "EURUSD",
    timeframe: "1h",
    start: "2024-01-01",
    end: "2024-12-31",
    initial_balance: 10_000,
    spread: 0.0001,
    slippage_pct: 0.0002,
    commission_pct: 0.0002,
    latency_bars: 1,
  });
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BacktestResult | null>(null);

  useEffect(() => {
    api
      .get<StrategySummary[]>("/api/strategies", { silent: true })
      .then((list) => {
        setStrategies(list);
        if (list.length > 0) {
          setForm((f) => (f.strategy_key ? f : { ...f, strategy_key: list[0].key }));
        }
      })
      .catch(() => setStrategies([]));
  }, []);

  const setField = (name: string, value: string | number) =>
    setForm((f) => ({ ...f, [name]: value }));

  const run = async (e: FormEvent) => {
    e.preventDefault();
    setRunning(true);
    setError(null);
    try {
      const response = await api.post<BacktestResult>(
        "/api/backtests/run",
        {
          strategy_key: form.strategy_key,
          symbol: form.symbol,
          timeframe: form.timeframe,
          start: form.start,
          end: form.end,
          initial_balance: form.initial_balance,
          params: {},
          frictions: {
            spread: form.spread,
            slippage_pct: form.slippage_pct,
            commission_pct: form.commission_pct,
            latency_bars: form.latency_bars,
          },
        },
        { silent: true },
      );
      setResult(response);
    } catch (err) {
      setResult(null);
      if (err instanceof ApiError && (err.status === 404 || err.status === 502)) {
        setError(
          "The backtester API is not available yet (service under construction). The form will work as soon as POST /api/backtests/run lands.",
        );
      } else {
        setError(err instanceof Error ? err.message : "Backtest failed.");
      }
    } finally {
      setRunning(false);
    }
  };

  const equityData = normalizeEquityCurve(result);

  return (
    <>
      <div className="page-head">
        <h1>Backtests</h1>
      </div>

      <div className="card">
        <SectionTitle>Run a backtest</SectionTitle>
        <form onSubmit={run}>
          <div className="form-grid">
            <div className="form-row">
              <label className="label" htmlFor="bt-strategy">
                Strategy
              </label>
              <select
                id="bt-strategy"
                className="input"
                required
                value={form.strategy_key}
                onChange={(e) => setField("strategy_key", e.target.value)}
              >
                <option value="">Select…</option>
                {strategies.map((s) => (
                  <option key={s.key} value={s.key}>
                    {s.name}
                  </option>
                ))}
              </select>
            </div>
            <TextField id="bt-symbol" label="Symbol" value={form.symbol} onChange={(v) => setField("symbol", v)} />
            <TextField id="bt-timeframe" label="Timeframe" value={form.timeframe} onChange={(v) => setField("timeframe", v)} />
            <DateField id="bt-start" label="Start" value={form.start} onChange={(v) => setField("start", v)} />
            <DateField id="bt-end" label="End" value={form.end} onChange={(v) => setField("end", v)} />
            <NumField id="bt-balance" label="Initial balance" value={form.initial_balance} step={100} onChange={(v) => setField("initial_balance", v)} />
            <NumField id="bt-spread" label="Spread" value={form.spread} step={0.0001} onChange={(v) => setField("spread", v)} />
            <NumField id="bt-slippage" label="Slippage (fraction)" value={form.slippage_pct} step={0.0001} onChange={(v) => setField("slippage_pct", v)} />
            <NumField id="bt-commission" label="Commission (fraction)" value={form.commission_pct} step={0.0001} onChange={(v) => setField("commission_pct", v)} />
            <NumField id="bt-latency" label="Latency (bars)" value={form.latency_bars} step={1} onChange={(v) => setField("latency_bars", v)} />
          </div>
          <button type="submit" className="btn btn-primary" disabled={running || !form.strategy_key}>
            {running ? "Running…" : "Run backtest"}
          </button>
        </form>
      </div>

      {error ? (
        <div style={{ marginTop: 16 }}>
          <ErrorBanner message={error} />
        </div>
      ) : null}

      {result ? (
        <>
          <SectionTitle>Results</SectionTitle>
          <div className="stat-grid">
            {METRIC_CARDS.map((card) => {
              const value = result.metrics?.[card.key];
              return (
                <StatCard
                  key={card.key}
                  label={card.label}
                  value={
                    value === null || value === undefined
                      ? "—"
                      : card.kind === "pct"
                        ? fmtPct(Number(value))
                        : fmtNum(Number(value), 3)
                  }
                  tone={toneFor(card.key, value)}
                />
              );
            })}
          </div>
          <div className="card" style={{ marginTop: 16 }}>
            <SectionTitle>Equity curve</SectionTitle>
            {equityData.length > 1 ? (
              <EquityCurveChart data={equityData} height={320} />
            ) : (
              <EmptyState title="The result did not include an equity curve" />
            )}
          </div>
        </>
      ) : null}
    </>
  );
}

function toneFor(key: string, value: unknown): "pos" | "neg" | "" {
  if (value === null || value === undefined) return "";
  const n = Number(value);
  if (Number.isNaN(n)) return "";
  if (key === "max_drawdown") return n > 0 ? "neg" : "";
  if (["sharpe", "sortino", "calmar", "cagr", "expectancy"].includes(key)) {
    return n > 0 ? "pos" : n < 0 ? "neg" : "";
  }
  if (key === "profit_factor") return n > 1 ? "pos" : n < 1 ? "neg" : "";
  return "";
}

/** Accepts equity_curve as number[] or [{timestamp, equity}] — the REST
 * contract is not final, so parse defensively. */
function normalizeEquityCurve(result: BacktestResult | null): EquitySample[] {
  if (!result || !Array.isArray(result.equity_curve)) return [];
  return result.equity_curve
    .map((point, i): EquitySample | null => {
      if (typeof point === "number") return { label: String(i), equity: point };
      if (point && typeof point === "object" && "equity" in point) {
        return {
          label:
            "timestamp" in point && point.timestamp !== undefined
              ? fmtDateTime(point.timestamp as string | number)
              : String(i),
          equity: Number((point as { equity: unknown }).equity),
        };
      }
      return null;
    })
    .filter((p): p is EquitySample => p !== null && !Number.isNaN(p.equity));
}

function TextField({ id, label, value, onChange }: { id: string; label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div className="form-row">
      <label className="label" htmlFor={id}>
        {label}
      </label>
      <input id={id} className="input" required value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

function DateField({ id, label, value, onChange }: { id: string; label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div className="form-row">
      <label className="label" htmlFor={id}>
        {label}
      </label>
      <input id={id} className="input" type="date" required value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

function NumField({ id, label, value, step, onChange }: { id: string; label: string; value: number; step: number; onChange: (v: number) => void }) {
  return (
    <div className="form-row">
      <label className="label" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        className="input"
        type="number"
        step={step}
        value={value}
        onChange={(e) => {
          const parsed = parseFloat(e.target.value);
          if (!Number.isNaN(parsed)) onChange(parsed);
        }}
      />
    </div>
  );
}
