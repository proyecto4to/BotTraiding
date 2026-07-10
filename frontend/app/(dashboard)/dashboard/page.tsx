"use client";

/**
 * Overview: equity/PnL/drawdown cards, open positions, circuit-breaker badge
 * and per-service health tiles. Polls the portfolio every 10s and builds a
 * session equity/drawdown series from the snapshots (display only — there is
 * no equity-history endpoint yet).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { DrawdownChart, type DrawdownSample } from "@/components/charts/DrawdownChart";
import { EquityCurveChart, type EquitySample } from "@/components/charts/EquityCurveChart";
import { PnlBarChart } from "@/components/charts/PnlBarChart";
import {
  Badge,
  EmptyState,
  ErrorBanner,
  LoadingSkeleton,
  SectionTitle,
  StatCard,
  circuitBreakerTone,
} from "@/components/ui";
import { api } from "@/lib/api";
import { fmtMoney, fmtPct, fmtTime, pnlClass } from "@/lib/format";
import { probeSystemHealth } from "@/lib/health";
import { useSettings } from "@/lib/settings";
import type { CircuitBreakerStatus, HealthTile, PortfolioState } from "@/lib/types";

const POLL_MS = 10_000;
const MAX_SAMPLES = 360;

export default function DashboardPage() {
  const { accountId } = useSettings();
  const [portfolio, setPortfolio] = useState<PortfolioState | null>(null);
  const [breaker, setBreaker] = useState<CircuitBreakerStatus | null>(null);
  const [health, setHealth] = useState<HealthTile[]>([]);
  const [loading, setLoading] = useState(true);
  const [portfolioError, setPortfolioError] = useState<string | null>(null);
  const equitySeries = useRef<EquitySample[]>([]);
  const drawdownSeries = useRef<DrawdownSample[]>([]);
  const [, forceRender] = useState(0);

  const load = useCallback(async () => {
    try {
      const state = await api.get<PortfolioState>(`/api/portfolio/${accountId}`, {
        silent: true,
      });
      setPortfolio(state);
      setPortfolioError(null);
      const label = fmtTime(Date.now());
      equitySeries.current = [
        ...equitySeries.current.slice(-(MAX_SAMPLES - 1)),
        { label, equity: state.account.equity },
      ];
      drawdownSeries.current = [
        ...drawdownSeries.current.slice(-(MAX_SAMPLES - 1)),
        { label, drawdown: state.drawdown.current_drawdown },
      ];
      forceRender((n) => n + 1);
    } catch {
      setPortfolioError("portfolio-engine is not responding; showing last known data.");
    }
    try {
      setBreaker(
        await api.get<CircuitBreakerStatus>(`/api/risk/circuit-breaker/${accountId}`, {
          silent: true,
        }),
      );
    } catch {
      setBreaker(null);
    }
    setLoading(false);
  }, [accountId]);

  useEffect(() => {
    equitySeries.current = [];
    drawdownSeries.current = [];
    setLoading(true);
    void load();
    const timer = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(timer);
  }, [load]);

  useEffect(() => {
    let cancelled = false;
    const probe = async () => {
      const tiles = await probeSystemHealth(accountId);
      if (!cancelled) setHealth(tiles);
    };
    void probe();
    const timer = setInterval(() => void probe(), 30_000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [accountId]);

  if (loading) return <LoadingSkeleton rows={6} />;

  const account = portfolio?.account;
  const dd = portfolio?.drawdown;

  return (
    <>
      <div className="page-head">
        <h1>Overview — {accountId}</h1>
        {breaker ? (
          <Badge tone={circuitBreakerTone(breaker.state)}>
            Circuit breaker: {breaker.state}
          </Badge>
        ) : (
          <Badge tone="neutral">Circuit breaker: unknown</Badge>
        )}
      </div>

      {portfolioError ? <ErrorBanner message={portfolioError} /> : null}

      <div className="stat-grid">
        <StatCard
          label="Equity"
          value={fmtMoney(account?.equity, account?.currency)}
          sub={`Balance ${fmtMoney(account?.balance, account?.currency)}`}
        />
        <StatCard
          label="Unrealized PnL"
          value={fmtMoney(portfolio?.unrealized_pnl, account?.currency)}
          tone={pnlClass(portfolio?.unrealized_pnl) as "pos" | "neg" | ""}
        />
        <StatCard
          label="Realized PnL"
          value={fmtMoney(portfolio?.realized_pnl, account?.currency)}
          tone={pnlClass(portfolio?.realized_pnl) as "pos" | "neg" | ""}
        />
        <StatCard
          label="Current drawdown"
          value={fmtPct(dd?.current_drawdown)}
          tone={dd && dd.current_drawdown > 0 ? "neg" : ""}
          sub={`Peak equity ${fmtMoney(dd?.peak_equity, account?.currency)}`}
        />
        <StatCard
          label="Floating drawdown"
          value={fmtPct(dd?.floating_drawdown)}
          tone={dd && dd.floating_drawdown > 0 ? "neg" : ""}
        />
        <StatCard
          label="Free margin"
          value={fmtMoney(account?.free_margin, account?.currency)}
          sub={`Margin used ${fmtMoney(account?.margin_used, account?.currency)}`}
        />
      </div>

      <div className="grid-2" style={{ marginTop: 16 }}>
        <div className="card">
          <SectionTitle>Equity (session)</SectionTitle>
          {equitySeries.current.length > 1 ? (
            <EquityCurveChart data={equitySeries.current} />
          ) : (
            <EmptyState
              title="Collecting equity samples…"
              hint="The curve builds from live snapshots every 10 seconds."
            />
          )}
        </div>
        <div className="card">
          <SectionTitle>Drawdown (session)</SectionTitle>
          {drawdownSeries.current.length > 1 ? (
            <DrawdownChart data={drawdownSeries.current} />
          ) : (
            <EmptyState title="Collecting drawdown samples…" />
          )}
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <SectionTitle>PnL by period</SectionTitle>
        {portfolio ? (
          <PnlBarChart
            data={[
              { label: "Daily", pnl: portfolio.pnl_daily },
              { label: "Weekly", pnl: portfolio.pnl_weekly },
              { label: "Monthly", pnl: portfolio.pnl_monthly },
            ]}
          />
        ) : (
          <EmptyState title="No PnL data" />
        )}
      </div>

      <SectionTitle>Open positions</SectionTitle>
      <div className="card table-wrap">
        {portfolio && portfolio.positions.length > 0 ? (
          <table className="table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Quantity</th>
                <th>Avg price</th>
                <th>Mark</th>
                <th>Unrealized PnL</th>
              </tr>
            </thead>
            <tbody>
              {portfolio.positions.map((p) => (
                <tr key={p.symbol}>
                  <td>{p.symbol}</td>
                  <td>{p.quantity}</td>
                  <td>{fmtMoney(p.average_price)}</td>
                  <td>{fmtMoney(portfolio.marks[p.symbol])}</td>
                  <td className={pnlClass(p.unrealized_pnl)}>{fmtMoney(p.unrealized_pnl)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <EmptyState title="No open positions" />
        )}
      </div>

      <SectionTitle>System health</SectionTitle>
      <div className="health-grid">
        {health.map((tile) => (
          <div className="health-tile" key={tile.service}>
            <span className={`health-dot ${tile.status}`} aria-hidden="true" />
            <span>{tile.service}</span>
            <span className="muted" style={{ marginLeft: "auto" }}>
              {tile.status}
            </span>
          </div>
        ))}
        {health.length === 0 ? <span className="muted">Probing services…</span> : null}
      </div>
    </>
  );
}
