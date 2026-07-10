"use client";

/**
 * Executions: order/execution history with status filters and a PROMINENT
 * Demo/Real (paper/live) indicator. The mode switch is admin-only and asks
 * for explicit confirmation — and it only changes the UI preference used
 * when composing orders; the execution-engine enforces the real gate
 * server-side (env default + admin-only override, /modes).
 */

import { useCallback, useEffect, useState } from "react";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { useToast } from "@/components/Toast";
import { Badge, EmptyState, ErrorBanner, LoadingSkeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDateTime, fmtMoney, fmtNum } from "@/lib/format";
import { useSettings } from "@/lib/settings";
import type { ExecutionOut, ModesResponse } from "@/lib/types";

const STATUSES = [
  "",
  "pending",
  "submitted",
  "partially_filled",
  "filled",
  "cancelled",
  "rejected",
  "error",
];

export default function ExecutionsPage() {
  const { accountId, uiMode, setUiMode } = useSettings();
  const { isAdmin } = useAuth();
  const { push } = useToast();

  const [executions, setExecutions] = useState<ExecutionOut[]>([]);
  const [modes, setModes] = useState<ModesResponse | null>(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirmLive, setConfirmLive] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const list = await api.get<ExecutionOut[]>("/api/executions/", {
        silent: true,
        query: { account_id: accountId, status: statusFilter },
      });
      setExecutions([...list].reverse()); // newest first
      setError(null);
    } catch {
      setError("execution-engine is not responding.");
      setExecutions([]);
    }
    try {
      setModes(await api.get<ModesResponse>("/api/executions/modes", { silent: true }));
    } catch {
      setModes(null);
    }
    setLoading(false);
  }, [accountId, statusFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const requestModeSwitch = () => {
    if (uiMode === "live") {
      setUiMode("paper");
      push("Switched to DEMO (paper) mode.", "success");
    } else {
      setConfirmLive(true);
    }
  };

  const isLive = uiMode === "live";

  return (
    <>
      <div className={`mode-banner ${isLive ? "live" : "paper"}`} role="status">
        <span className="mode-word">{isLive ? "REAL — LIVE TRADING" : "DEMO — PAPER TRADING"}</span>
        {modes ? (
          <span className="muted">
            server default: {modes.default_mode}
            {modes.override_requires_admin ? " · override requires admin" : ""}
          </span>
        ) : (
          <span className="muted">server mode config unavailable</span>
        )}
        {isAdmin ? (
          <button
            type="button"
            className={isLive ? "btn" : "btn btn-danger"}
            style={{ marginLeft: "auto" }}
            onClick={requestModeSwitch}
          >
            {isLive ? "Switch to DEMO" : "Switch to REAL"}
          </button>
        ) : (
          <span className="muted" style={{ marginLeft: "auto" }}>
            mode switch is admin-only
          </span>
        )}
      </div>

      <div className="page-head">
        <h1>Executions — {accountId}</h1>
        <div className="filters-row" style={{ marginBottom: 0 }}>
          <div className="form-row">
            <label className="label" htmlFor="exec-status">
              Status
            </label>
            <select
              id="exec-status"
              className="input input-sm"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
            >
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s === "" ? "All" : s}
                </option>
              ))}
            </select>
          </div>
          <button type="button" className="btn" onClick={() => void load()}>
            Refresh
          </button>
        </div>
      </div>

      {error ? <ErrorBanner message={error} /> : null}

      {loading ? (
        <LoadingSkeleton rows={5} />
      ) : executions.length === 0 ? (
        <EmptyState
          title="No executions"
          hint="Executions appear here once the trading engine submits approved orders."
        />
      ) : (
        <div className="card table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Created</th>
                <th>Symbol</th>
                <th>Side</th>
                <th>Qty</th>
                <th>Filled</th>
                <th>Avg fill</th>
                <th>Type</th>
                <th>Broker</th>
                <th>Mode</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {executions.map((e) => (
                <tr key={e.id}>
                  <td>{fmtDateTime(e.created_at)}</td>
                  <td>{e.symbol}</td>
                  <td className={e.side === "buy" ? "pos" : "neg"}>{e.side.toUpperCase()}</td>
                  <td>{fmtNum(e.quantity, 4)}</td>
                  <td>{fmtNum(e.filled_quantity, 4)}</td>
                  <td>{fmtMoney(e.average_fill_price)}</td>
                  <td>{e.order_type}</td>
                  <td>{e.broker}</td>
                  <td>
                    {e.execution_mode === "live" ? (
                      <Badge tone="red">LIVE</Badge>
                    ) : (
                      <Badge tone="accent">paper</Badge>
                    )}
                  </td>
                  <td>
                    <Badge tone={statusTone(e.status)}>{e.status}</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <ConfirmDialog
        open={confirmLive}
        title="Switch to REAL (live) mode?"
        danger
        confirmLabel="I understand — switch to REAL"
        body={
          <>
            <p>
              <strong>Warning:</strong> orders composed in REAL mode are sent to live broker
              accounts with real money. Every order still passes the risk-engine and the
              execution-engine's admin gate, but fills are irreversible.
            </p>
            <p>
              The platform's mandatory progression is backtest → paper → real. Only switch if
              this strategy has passed paper trading.
            </p>
          </>
        }
        onConfirm={() => {
          setConfirmLive(false);
          setUiMode("live");
          push("REAL (live) mode enabled for this browser.", "error");
        }}
        onCancel={() => setConfirmLive(false)}
      />
    </>
  );
}

function statusTone(status: string): "green" | "red" | "amber" | "neutral" {
  switch (status) {
    case "filled":
      return "green";
    case "rejected":
    case "error":
      return "red";
    case "partially_filled":
    case "submitted":
    case "pending":
      return "amber";
    default:
      return "neutral";
  }
}
