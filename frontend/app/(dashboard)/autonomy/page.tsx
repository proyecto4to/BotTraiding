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
import { api } from "@/lib/api";
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
  selection: { symbol: string; strategy_key: string; weight: number; category?: string }[];
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
  const [loading, setLoading] = useState(true);
  const [toggling, setToggling] = useState(false);

  const load = useCallback(async () => {
    const [st, dec, bt] = await Promise.allSettled([
      api.get<AutomationState>("/api/automation/state", { silent: true }),
      api.get<Decision[]>("/api/automation/decisions", { silent: true, query: { limit: 20 } }),
      api.get<Bot[]>("/api/bots", { silent: true, query: { account_id: AUTONOMY_ACCOUNT } }),
    ]);
    if (st.status === "fulfilled") setAutomation(st.value);
    if (dec.status === "fulfilled") setDecisions(Array.isArray(dec.value) ? dec.value : []);
    if (bt.status === "fulfilled") {
      const list = Array.isArray(bt.value) ? bt.value : [];
      setBots(list.filter((b) => b.name?.startsWith("auto:")));
    }
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
                  <tr><th>Symbol</th><th>Strategy</th><th>Category</th><th>Weight</th></tr>
                </thead>
                <tbody>
                  {latest.selection.map((s, i) => (
                    <tr key={`${s.symbol}:${s.strategy_key}:${i}`}>
                      <td>{s.symbol}</td>
                      <td style={{ fontFamily: "var(--mono)" }}>{s.strategy_key}</td>
                      <td>{s.category ?? "—"}</td>
                      <td>{(s.weight * 100).toFixed(0)}%</td>
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
