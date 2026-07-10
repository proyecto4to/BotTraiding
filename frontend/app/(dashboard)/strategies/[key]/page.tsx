"use client";

/**
 * Strategy detail: metadata, enable toggle and the parameter config editor.
 * The param form renders the strategy's published schema; overrides are
 * saved per user/account via PUT /api/strategies/{key}/config and validated
 * server-side by the strategy-engine.
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ParamSchemaForm, type ParamValues } from "@/components/ParamSchemaForm";
import { useToast } from "@/components/Toast";
import { Badge, EmptyState, ErrorBanner, LoadingSkeleton, SectionTitle } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtNum } from "@/lib/format";
import { useSettings } from "@/lib/settings";
import type { StrategyConfigResponse, StrategyDetail } from "@/lib/types";

export default function StrategyDetailPage() {
  const params = useParams<{ key: string }>();
  const strategyKey = decodeURIComponent(params.key);
  const { state } = useAuth();
  const { accountId } = useSettings();
  const { push } = useToast();

  const [detail, setDetail] = useState<StrategyDetail | null>(null);
  const [overrides, setOverrides] = useState<ParamValues>({});
  const [configActive, setConfigActive] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const userId = state.user?.id ?? "";

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await api.get<StrategyDetail>(
        `/api/strategies/${encodeURIComponent(strategyKey)}`,
        { silent: true },
      );
      setDetail(d);
      setError(null);
      try {
        const config = await api.get<StrategyConfigResponse>(
          `/api/strategies/${encodeURIComponent(strategyKey)}/config`,
          { silent: true, query: { user_id: userId, account_id: accountId } },
        );
        setOverrides(config.overrides);
        setConfigActive(config.is_active);
      } catch (err) {
        // 404 = no saved config yet: start from defaults.
        if (!(err instanceof ApiError && err.status === 404)) throw err;
        setOverrides({});
      }
    } catch {
      setError("strategy-engine is not responding.");
    } finally {
      setLoading(false);
    }
  }, [strategyKey, userId, accountId]);

  useEffect(() => {
    if (userId) void load();
  }, [load, userId]);

  const save = async () => {
    setSaving(true);
    try {
      await api.put<StrategyConfigResponse>(
        `/api/strategies/${encodeURIComponent(strategyKey)}/config`,
        {
          user_id: userId,
          account_id: accountId,
          overrides,
          is_active: configActive,
        },
      );
      push("Configuration saved.", "success");
    } catch {
      /* api client already toasted the validation error */
    } finally {
      setSaving(false);
    }
  };

  const toggleEnabled = async () => {
    if (!detail) return;
    try {
      const updated = await api.patch<StrategyDetail>(
        `/api/strategies/${encodeURIComponent(strategyKey)}`,
        { enabled: !detail.enabled },
      );
      setDetail({ ...detail, enabled: updated.enabled });
      push(`Strategy ${updated.enabled ? "enabled" : "disabled"}.`, "success");
    } catch {
      /* toasted */
    }
  };

  if (loading) return <LoadingSkeleton rows={6} />;

  if (!detail) {
    return (
      <>
        <p>
          <Link href="/strategies">← Strategies</Link>
        </p>
        {error ? <ErrorBanner message={error} /> : null}
        <EmptyState title={`Strategy '${strategyKey}' unavailable`} />
      </>
    );
  }

  return (
    <>
      <p>
        <Link href="/strategies">← Strategies</Link>
      </p>
      <div className="page-head">
        <h1>{detail.name}</h1>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {detail.enabled ? <Badge tone="green">active</Badge> : <Badge tone="neutral">off</Badge>}
          <button type="button" className="btn" onClick={() => void toggleEnabled()}>
            {detail.enabled ? "Disable" : "Enable"}
          </button>
        </div>
      </div>

      <div className="grid-2">
        <div className="card">
          <SectionTitle>Metadata</SectionTitle>
          <ul className="kv-list">
            <li>
              <span>Key</span>
              <span>{detail.key}</span>
            </li>
            <li>
              <span>Version</span>
              <span>{detail.version}</span>
            </li>
            <li>
              <span>Category</span>
              <span>{detail.category}</span>
            </li>
            <li>
              <span>Markets</span>
              <span>{detail.markets.join(", ")}</span>
            </li>
            <li>
              <span>Timeframes</span>
              <span>{detail.timeframes.join(", ")}</span>
            </li>
            <li>
              <span>Recommended risk/trade</span>
              <span>{fmtNum(detail.recommended_risk_per_trade * 100)}%</span>
            </li>
          </ul>
          <p className="muted" style={{ marginTop: 10 }}>
            {detail.description}
          </p>

          {Object.keys(detail.historical_metrics).length > 0 ? (
            <>
              <SectionTitle>Historical metrics</SectionTitle>
              <ul className="kv-list">
                {Object.entries(detail.historical_metrics).map(([k, v]) => (
                  <li key={k}>
                    <span>{k}</span>
                    <span>{fmtNum(v, 4)}</span>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
        </div>

        <div className="card">
          <SectionTitle>Parameters — account {accountId}</SectionTitle>
          <ParamSchemaForm
            schema={detail.parameters}
            values={overrides}
            onChange={setOverrides}
          />
          <div className="form-row" style={{ marginTop: 12 }}>
            <label className="label" htmlFor="config-active">
              Config active
            </label>
            <input
              id="config-active"
              type="checkbox"
              className="toggle"
              checked={configActive}
              onChange={(e) => setConfigActive(e.target.checked)}
            />
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button
              type="button"
              className="btn btn-primary"
              disabled={saving}
              onClick={() => void save()}
            >
              {saving ? "Saving…" : "Save configuration"}
            </button>
            <button type="button" className="btn" onClick={() => setOverrides({})}>
              Reset to defaults
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
