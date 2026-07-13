"use client";

/**
 * Autonomy panel (P10): what the self-driving system is doing and why.
 *
 * - The master switch (enable/disable) — admin only.
 * - Current state + recommendation.
 * - The latest regime the AI detected and the strategy selection it produced.
 * - The autonomy-owned bots currently live.
 * - A timeline of recent automated decisions.
 *
 * All data comes through the gateway; every call degrades to an empty state so
 * the page never crashes when the controller is still coming up.
 */

import { useCallback, useEffect, useState } from "react";
import { Badge, EmptyState, LoadingSkeleton, SectionTitle } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDateTime } from "@/lib/format";

const POLL_MS = 15_000;
const AUTONOMY_ACCOUNT = "autonomy";

interface AutomationState {
  enabled: boolean;
  mode: string;
  recommendation: string;
}

interface Decision {
  id: string;
  created_at: string;
  state: string;
  summary: string;
  regime: Record<string, { trend?: string; volatility?: string; confidence?: number }>;
  selection: {
    symbol: string;
    strategy_key: string;
    weight: number;
    category?: string;
    capital_fraction?: number;
    risk_per_trade?: number;
  }[];
  actions: { action: string; bot: string }[];
  errors: unknown[];
}

interface Bot {
  id: string;
  name: string;
  status: string;
  symbols: string[];
  strategy_keys: string[];
}

interface Readiness {
  ready: boolean;
  state: string;
  gates: { name: string; passed: boolean; detail: string }[];
}

function stateTone(mode: string): "green" | "amber" | "red" | "neutral" {
  const m = mode.toLowerCase();
  if (m === "trading_paper" || m === "trading_live") return "green";
  if (m === "learning") return "amber";
  if (m === "halted" || m === "unavailable") return "red";
  return "neutral";
}

export default function AutonomyPage() {
  const { state: auth } = useAuth();
  const isAdmin = auth.user?.roles?.includes("admin") ?? false;

  const [automation, setAutomation] = useState<AutomationState | null>(null);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [bots, setBots] = useState<Bot[]>([]);
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [loading, setLoading] = useState(true);
  const [toggling, setToggling] = useState(false);
  const [promoting, setPromoting] = useState(false);

  const load = useCallback(async () => {
    const [st, dec, bt, rd] = await Promise.allSettled([
      api.get<AutomationState>("/api/automation/state", { silent: true }),
      api.get<Decision[]>("/api/automation/decisions", { silent: true, query: { limit: 20 } }),
      api.get<Bot[]>("/api/bots", { silent: true, query: { account_id: AUTONOMY_ACCOUNT } }),
      api.get<Readiness>("/api/automation/readiness", { silent: true }),
    ]);
    if (st.status === "fulfilled") setAutomation(st.value);
    if (dec.status === "fulfilled") setDecisions(Array.isArray(dec.value) ? dec.value : []);
    if (bt.status === "fulfilled") {
      const list = Array.isArray(bt.value) ? bt.value : [];
      setBots(list.filter((b) => b.name?.startsWith("auto:")));
    }
    if (rd.status === "fulfilled") setReadiness(rd.value);
    setLoading(false);
  }, []);

  useEffect(() => {
    setLoading(true);
    void load();
    const timer = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(timer);
  }, [load]);

  const toggle = async () => {
    setToggling(true);
    try {
      const next = await api.post<AutomationState>("/api/automation/toggle", undefined, {
        silent: true,
      });
      setAutomation(next);
      void load();
    } finally {
      setToggling(false);
    }
  };

  const promoteLive = async () => {
    if (
      !window.confirm(
        "Promote automation to LIVE (real money)? This is only allowed once every " +
          "paper-trading gate passes, and can be reverted with the kill switch.",
      )
    )
      return;
    setPromoting(true);
    try {
      await api.post("/api/automation/promote-live", undefined, { silent: true });
      void load();
    } catch (err) {
      const msg = err instanceof ApiError ? String(err.detail ?? err.message) : "Promotion failed";
      window.alert(`Cannot go live: ${msg}`);
    } finally {
      setPromoting(false);
    }
  };

  const latest = decisions[0];
  const regimeEntries = latest ? Object.entries(latest.regime ?? {}) : [];

  return (
    <>
      <div className="page-head">
        <h1>Autonomy</h1>
        <span className="muted">refreshes every 15s</span>
      </div>

      {/* Master switch */}
      <div className="card" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <Badge tone={stateTone(automation?.mode ?? "")}>
              {(automation?.mode ?? "unknown").toUpperCase()}
            </Badge>
            <span style={{ fontWeight: 600 }}>
              {automation?.enabled ? "The system is trading on its own" : "Automation is off"}
            </span>
          </div>
          <div className="muted" style={{ marginTop: 6 }}>
            {automation?.recommendation ?? "Waiting for the autonomy controller…"}
          </div>
        </div>
        <button
          type="button"
          className={`btn ${automation?.enabled ? "" : "btn-primary"}`}
          disabled={!isAdmin || toggling || automation?.mode === "unavailable"}
          title={isAdmin ? "" : "Only the operator (admin) can control automation"}
          onClick={toggle}
        >
          {toggling ? "Working…" : automation?.enabled ? "Disable automation" : "Enable automation"}
        </button>
      </div>

      {/* Paper -> live readiness (P18) */}
      {readiness && readiness.gates.length > 0 ? (
        <div className="card" style={{ marginTop: 16 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <Badge tone={readiness.ready ? "green" : "amber"}>
                {readiness.ready ? "READY FOR LIVE" : "NOT READY FOR LIVE"}
              </Badge>
              <span className="muted">
                {readiness.ready
                  ? "All paper-trading gates pass."
                  : "Live trading stays locked until every gate passes."}
              </span>
            </div>
            {isAdmin ? (
              <button
                type="button"
                className="btn"
                disabled={!readiness.ready || promoting || automation?.mode === "trading_live"}
                onClick={promoteLive}
              >
                {promoting ? "Promoting…" : "Promote to live"}
              </button>
            ) : null}
          </div>
          <div className="table-wrap" style={{ marginTop: 10 }}>
            <table className="table">
              <tbody>
                {readiness.gates.map((g) => (
                  <tr key={g.name}>
                    <td style={{ width: 24 }}>
                      <Badge tone={g.passed ? "green" : "red"}>{g.passed ? "✓" : "✗"}</Badge>
                    </td>
                    <td style={{ fontFamily: "var(--mono)" }}>{g.name}</td>
                    <td className="muted">{g.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      {loading ? (
        <LoadingSkeleton rows={4} />
      ) : (
        <>
          <SectionTitle>Current regime</SectionTitle>
          {regimeEntries.length === 0 ? (
            <EmptyState
              title="No regime yet"
              hint="Once automation is on, the AI's market-regime read for each symbol appears here."
            />
          ) : (
            <div className="card table-wrap">
              <table className="table">
                <thead>
                  <tr><th>Symbol</th><th>Trend</th><th>Volatility</th><th>Confidence</th></tr>
                </thead>
                <tbody>
                  {regimeEntries.map(([symbol, r]) => (
                    <tr key={symbol}>
                      <td>{symbol}</td>
                      <td>{r.trend ?? "—"}</td>
                      <td>{r.volatility ?? "—"}</td>
                      <td>{r.confidence != null ? `${(r.confidence * 100).toFixed(0)}%` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <SectionTitle>Selected strategies</SectionTitle>
          {!latest || latest.selection.length === 0 ? (
            <EmptyState title="No strategies selected" hint="The AI's weighted picks for the current regime show here." />
          ) : (
            <div className="card table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Symbol</th><th>Strategy</th><th>Category</th>
                    <th>Weight</th><th>Capital</th><th>Risk/trade</th>
                  </tr>
                </thead>
                <tbody>
                  {latest.selection.map((s, i) => (
                    <tr key={`${s.symbol}:${s.strategy_key}:${i}`}>
                      <td>{s.symbol}</td>
                      <td style={{ fontFamily: "var(--mono)" }}>{s.strategy_key}</td>
                      <td>{s.category ?? "—"}</td>
                      <td>{(s.weight * 100).toFixed(0)}%</td>
                      <td>{s.capital_fraction != null ? `${(s.capital_fraction * 100).toFixed(0)}%` : "—"}</td>
                      <td>{s.risk_per_trade != null ? `${(s.risk_per_trade * 100).toFixed(2)}%` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <SectionTitle>Live bots</SectionTitle>
          {bots.length === 0 ? (
            <EmptyState title="No autonomy bots running" hint="Bots the system starts automatically appear here." />
          ) : (
            <div className="card table-wrap">
              <table className="table">
                <thead>
                  <tr><th>Bot</th><th>Symbols</th><th>Strategies</th><th>Status</th></tr>
                </thead>
                <tbody>
                  {bots.map((b) => (
                    <tr key={b.id}>
                      <td style={{ fontFamily: "var(--mono)" }}>{b.name}</td>
                      <td>{(b.symbols ?? []).join(", ")}</td>
                      <td>{(b.strategy_keys ?? []).join(", ")}</td>
                      <td>
                        <Badge tone={b.status === "running" ? "green" : b.status === "error" ? "red" : "neutral"}>
                          {b.status}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <SectionTitle>Recent decisions</SectionTitle>
          {decisions.length === 0 ? (
            <EmptyState
              title="No decisions yet"
              hint="Every automated cycle is recorded here with what it decided and why."
            />
          ) : (
            <div className="card table-wrap">
              <table className="table">
                <thead>
                  <tr><th>When</th><th>State</th><th>Summary</th><th>Actions</th><th>Errors</th></tr>
                </thead>
                <tbody>
                  {decisions.map((d) => (
                    <tr key={d.id}>
                      <td>{fmtDateTime(d.created_at)}</td>
                      <td><Badge tone={stateTone(d.state.toLowerCase())}>{d.state}</Badge></td>
                      <td>{d.summary}</td>
                      <td>{d.actions?.length ?? 0}</td>
                      <td style={{ color: d.errors?.length ? "var(--red)" : undefined }}>
                        {d.errors?.length ?? 0}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </>
  );
}
