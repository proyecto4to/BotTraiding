"use client";

/**
 * Risk limits (all ExtendedRiskLimits fields) + circuit breaker state.
 * GET /api/risk/limits/{account}; PUT is admin-only; the breaker reset is
 * admin-only and confirmed explicitly. Configuration UI only — enforcement
 * lives in the risk-engine.
 */

import { useCallback, useEffect, useState } from "react";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { useToast } from "@/components/Toast";
import {
  Badge,
  EmptyState,
  ErrorBanner,
  LoadingSkeleton,
  SectionTitle,
  circuitBreakerTone,
} from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDateTime } from "@/lib/format";
import { useSettings } from "@/lib/settings";
import type { CircuitBreakerStatus, ExtendedRiskLimits, RiskLimitsResponse } from "@/lib/types";

/** Fraction-of-equity fields (0.02 = 2%). */
const FRACTION_FIELDS: [keyof ExtendedRiskLimits, string][] = [
  ["max_risk_per_trade", "Max risk per trade"],
  ["max_daily_loss", "Max daily loss"],
  ["max_weekly_loss", "Max weekly loss"],
  ["max_monthly_loss", "Max monthly loss"],
  ["max_drawdown", "Max drawdown"],
  ["max_floating_drawdown", "Max floating drawdown"],
  ["max_exposure_per_symbol", "Max exposure per symbol"],
  ["max_exposure_per_sector", "Max exposure per sector"],
];

const RATIO_FIELDS: [keyof ExtendedRiskLimits, string][] = [
  ["max_leverage", "Max leverage"],
  ["max_correlation", "Max correlation"],
  ["max_total_exposure", "Max total exposure"],
  ["min_volume", "Min volume (0 disables)"],
];

const OPTIONAL_FIELDS: [keyof ExtendedRiskLimits, string][] = [
  ["max_slippage", "Max slippage (blank disables)"],
  ["max_volatility", "Max volatility (blank disables)"],
];

export default function RiskPage() {
  const { accountId } = useSettings();
  const { isAdmin } = useAuth();
  const { push } = useToast();

  const [limits, setLimits] = useState<ExtendedRiskLimits | null>(null);
  const [isDefault, setIsDefault] = useState(false);
  const [thresholdsJson, setThresholdsJson] = useState("{}");
  const [breaker, setBreaker] = useState<CircuitBreakerStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await api.get<RiskLimitsResponse>(`/api/risk/limits/${accountId}`, {
        silent: true,
      });
      setLimits(response.limits);
      setIsDefault(response.is_default);
      setThresholdsJson(JSON.stringify(response.limits.circuit_breaker_thresholds, null, 2));
      setError(null);
    } catch {
      setError("risk-engine is not responding.");
      setLimits(null);
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
    void load();
  }, [load]);

  const setField = (name: keyof ExtendedRiskLimits, value: number | null) => {
    setLimits((current) => (current ? { ...current, [name]: value } : current));
  };

  const save = async () => {
    if (!limits) return;
    let thresholds: Record<string, number>;
    try {
      thresholds = JSON.parse(thresholdsJson || "{}");
    } catch {
      push("Circuit-breaker thresholds must be valid JSON.", "error");
      return;
    }
    setSaving(true);
    try {
      const response = await api.put<RiskLimitsResponse>(`/api/risk/limits/${accountId}`, {
        ...limits,
        circuit_breaker_thresholds: thresholds,
      });
      setLimits(response.limits);
      setIsDefault(response.is_default);
      push("Risk limits saved.", "success");
    } catch {
      /* toasted by api client (403 for non-admin, 422 for bad values) */
    } finally {
      setSaving(false);
    }
  };

  const resetBreaker = async () => {
    setConfirmReset(false);
    try {
      const status = await api.post<CircuitBreakerStatus>(
        `/api/risk/circuit-breaker/${accountId}/reset`,
      );
      setBreaker(status);
      push("Circuit breaker reset to NORMAL.", "success");
    } catch {
      /* toasted */
    }
  };

  if (loading) return <LoadingSkeleton rows={6} />;

  return (
    <>
      <div className="page-head">
        <h1>Risk — {accountId}</h1>
        {isDefault ? <Badge tone="amber">default limits (not yet saved)</Badge> : null}
      </div>

      {error ? <ErrorBanner message={error} /> : null}

      <div className="card">
        <SectionTitle>Circuit breaker</SectionTitle>
        {breaker ? (
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <Badge tone={circuitBreakerTone(breaker.state)}>{breaker.state}</Badge>
            <span className="muted">
              {breaker.reason ?? "no incident"} · errors: {breaker.error_count} · updated{" "}
              {fmtDateTime(breaker.updated_at)}
            </span>
            {isAdmin ? (
              <button
                type="button"
                className="btn btn-danger"
                style={{ marginLeft: "auto" }}
                onClick={() => setConfirmReset(true)}
              >
                Reset breaker
              </button>
            ) : (
              <span className="muted" style={{ marginLeft: "auto" }}>
                admin role required to reset
              </span>
            )}
          </div>
        ) : (
          <EmptyState title="Circuit breaker state unavailable" />
        )}
      </div>

      {limits ? (
        <div className="card" style={{ marginTop: 16 }}>
          <SectionTitle>Risk limits</SectionTitle>
          {!isAdmin ? (
            <div className="banner banner-warn">
              Read-only: saving risk limits requires the admin role.
            </div>
          ) : null}

          <h3 className="muted" style={{ fontSize: "0.8rem" }}>
            Fractions of equity (0.02 = 2%)
          </h3>
          <div className="form-grid">
            {FRACTION_FIELDS.map(([name, label]) => (
              <NumberField
                key={name}
                id={`limit-${name}`}
                label={label}
                value={limits[name] as number}
                step={0.005}
                onChange={(v) => setField(name, v ?? 0)}
              />
            ))}
          </div>

          <h3 className="muted" style={{ fontSize: "0.8rem", marginTop: 16 }}>
            Ratios / absolute
          </h3>
          <div className="form-grid">
            {RATIO_FIELDS.map(([name, label]) => (
              <NumberField
                key={name}
                id={`limit-${name}`}
                label={label}
                value={limits[name] as number}
                step={0.1}
                onChange={(v) => setField(name, v ?? 0)}
              />
            ))}
            {OPTIONAL_FIELDS.map(([name, label]) => (
              <NumberField
                key={name}
                id={`limit-${name}`}
                label={label}
                value={limits[name] as number | null}
                step={0.01}
                nullable
                onChange={(v) => setField(name, v)}
              />
            ))}
          </div>

          <div className="form-row" style={{ marginTop: 16 }}>
            <label className="label" htmlFor="limit-thresholds">
              Circuit-breaker thresholds (JSON)
            </label>
            <textarea
              id="limit-thresholds"
              className="input"
              value={thresholdsJson}
              onChange={(e) => setThresholdsJson(e.target.value)}
              spellCheck={false}
            />
          </div>

          <button
            type="button"
            className="btn btn-primary"
            disabled={saving || !isAdmin}
            onClick={() => void save()}
          >
            {saving ? "Saving…" : "Save limits"}
          </button>
        </div>
      ) : null}

      <ConfirmDialog
        open={confirmReset}
        title="Reset circuit breaker?"
        danger
        confirmLabel="Reset to NORMAL"
        body={
          <p>
            This forces the breaker for account <strong>{accountId}</strong> back to NORMAL and
            re-enables trading. The action is audited by the risk-engine. Only do this after the
            underlying incident is understood.
          </p>
        }
        onConfirm={() => void resetBreaker()}
        onCancel={() => setConfirmReset(false)}
      />
    </>
  );
}

function NumberField({
  id,
  label,
  value,
  step,
  nullable = false,
  onChange,
}: {
  id: string;
  label: string;
  value: number | null;
  step: number;
  nullable?: boolean;
  onChange: (value: number | null) => void;
}) {
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
        value={value === null || value === undefined ? "" : value}
        onChange={(e) => {
          const raw = e.target.value;
          if (raw === "") {
            onChange(nullable ? null : 0);
            return;
          }
          const parsed = parseFloat(raw);
          if (!Number.isNaN(parsed)) onChange(parsed);
        }}
      />
    </div>
  );
}
